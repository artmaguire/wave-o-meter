"""Lightweight access gate (single shared-secret question).

Intended as a low-effort deterrent for a publicly-reachable home-server URL —
enough to turn away scanners and casual visitors. It is NOT strong security:
  * one shared answer, no per-user accounts
  * value comes only if served over HTTPS (else the answer + token are plaintext)
Put this behind a TLS-terminating reverse proxy for a public URL.

Design:
  * The answer is checked SERVER-SIDE only; it is never sent to the browser.
  * On success we set an HMAC-signed, expiring session cookie. The signing key
    comes from GATE_SECRET (env); if unset, a random per-process key is used
    (tokens survive only until restart) — the key is NEVER derived from the
    answer, so a known answer cannot forge tokens.
  * Guesses are rate-limited per client IP: GATE_MAX_TRIES then a lockout.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time

log = logging.getLogger("waveometer.auth")

# Config (env-overridable). The answer defaults to the owner's; override in prod.
GATE_ENABLED = os.environ.get("GATE_ENABLED", "1") not in ("0", "false", "False")
GATE_QUESTION = os.environ.get("GATE_QUESTION", "What is the name of my surfboard?")
# No committed default — the real answer lives only in the server .env.
_GATE_ANSWER = os.environ.get("GATE_ANSWER", "")
GATE_MAX_TRIES = int(os.environ.get("GATE_MAX_TRIES", "3"))
GATE_LOCKOUT_S = int(os.environ.get("GATE_LOCKOUT_S", "900"))   # 15 min
GATE_SESSION_S = int(os.environ.get("GATE_SESSION_S", str(30 * 24 * 3600)))  # 30d
COOKIE_NAME = "wom_gate"

# Signing key. Prefer GATE_SECRET (stable across restarts). If unset, generate a
# random per-process key so tokens are never forgeable from a known answer — the
# tradeoff is sessions drop on restart. NEVER derive the key from the answer.
_env_secret = os.environ.get("GATE_SECRET", "").strip()
if _env_secret:
    _SECRET = _env_secret.encode()
else:
    _SECRET = secrets.token_bytes(32)
    if GATE_ENABLED:
        log.warning("GATE_SECRET not set — using a random per-process key; "
                    "gate sessions will not survive restarts. Set GATE_SECRET.")

# In-memory per-IP attempt tracking: ip -> (fail_count, first_fail_ts).
_attempts: dict[str, tuple[int, float]] = {}


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def is_locked(ip: str) -> tuple[bool, int]:
    """(locked, seconds_remaining) for an IP."""
    rec = _attempts.get(ip)
    if not rec:
        return False, 0
    count, first = rec
    if count < GATE_MAX_TRIES:
        return False, 0
    remaining = int(GATE_LOCKOUT_S - (time.time() - first))
    if remaining <= 0:
        _attempts.pop(ip, None)  # lockout expired
        return False, 0
    return True, remaining


def register_failure(ip: str) -> int:
    """Record a wrong guess; return tries remaining before lockout."""
    count, first = _attempts.get(ip, (0, time.time()))
    count += 1
    _attempts[ip] = (count, first)
    return max(0, GATE_MAX_TRIES - count)


def clear(ip: str) -> None:
    _attempts.pop(ip, None)


def check_answer(answer: str) -> bool:
    # Fail closed if no answer is configured (misconfiguration shouldn't let
    # everyone in). Constant-time compare on normalised values.
    if not _GATE_ANSWER:
        return False
    return hmac.compare_digest(_norm(answer), _norm(_GATE_ANSWER))


def issue_token() -> str:
    """Signed token: expiry.hexmac."""
    exp = str(int(time.time()) + GATE_SESSION_S)
    mac = hmac.new(_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{mac}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, mac = token.rsplit(".", 1)
    expected = hmac.new(_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False
