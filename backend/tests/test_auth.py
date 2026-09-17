"""Security-critical tests for the access gate (auth.py).

A regression here could silently open the gate, so these lock in: token
signing/verification, the tamper/forgery guards, expiry, the per-IP lockout,
and answer checking (incl. fail-closed when unconfigured).
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# env vars auth reads — cleared before each reload so tests don't leak into
# each other (they run in one process).
_AUTH_ENV = ["GATE_SECRET", "GATE_ANSWER", "GATE_ENABLED", "GATE_MAX_TRIES",
             "GATE_LOCKOUT_S", "GATE_SESSION_S", "GATE_QUESTION"]


def _fresh_auth(secret="unit-test-secret", answer="Dmitrius", **extra):
    """Reload auth with a clean, controlled environment."""
    for k in _AUTH_ENV:
        os.environ.pop(k, None)
    os.environ["GATE_SECRET"] = secret
    os.environ["GATE_ANSWER"] = answer
    os.environ["GATE_ENABLED"] = "1"
    for k, v in extra.items():
        os.environ[k] = v
    from app import auth
    return importlib.reload(auth)


def test_valid_token_roundtrips():
    a = _fresh_auth()
    assert a.verify_token(a.issue_token()) is True


def test_tampered_token_rejected():
    a = _fresh_auth()
    tok = a.issue_token()
    exp, mac = tok.rsplit(".", 1)
    # flip the mac
    bad = f"{exp}.{'0' * len(mac)}"
    assert a.verify_token(bad) is False


def test_answer_derived_key_cannot_forge():
    """The old vuln: a key derived from the (known) answer must NOT verify."""
    import hashlib
    import hmac
    a = _fresh_auth(secret="a-proper-random-secret", answer="Dmitrius")
    exp = str(int(time.time()) + 3600)
    forged_key = hashlib.sha256(b"wom-gate-v1::Dmitrius").hexdigest().encode()
    forged = f"{exp}." + hmac.new(forged_key, exp.encode(), hashlib.sha256).hexdigest()
    assert a.verify_token(forged) is False


def test_expired_token_rejected():
    a = _fresh_auth(GATE_SESSION_S="-1")  # already expired on issue
    assert a.verify_token(a.issue_token()) is False


def test_malformed_tokens_rejected():
    a = _fresh_auth()
    for bad in [None, "", "no-dot", "abc.def", "123.", ".mac"]:
        assert a.verify_token(bad) is False


def test_answer_check_case_and_space_insensitive():
    a = _fresh_auth(answer="Dmitrius")
    assert a.check_answer("  dmitrius ") is True
    assert a.check_answer("DMITRIUS") is True
    assert a.check_answer("wrong") is False


def test_fail_closed_when_no_answer_configured():
    a = _fresh_auth(answer="")
    # even an empty guess must not pass when the gate is misconfigured
    assert a.check_answer("") is False
    assert a.check_answer("anything") is False


def test_lockout_after_max_tries():
    a = _fresh_auth(GATE_MAX_TRIES="3", GATE_LOCKOUT_S="900")
    ip = "10.0.0.1"
    a.clear(ip)
    assert a.is_locked(ip) == (False, 0)
    for _ in range(3):
        a.register_failure(ip)
    locked, remaining = a.is_locked(ip)
    assert locked is True and remaining > 0


def test_clear_resets_lockout():
    a = _fresh_auth(GATE_MAX_TRIES="3")
    ip = "10.0.0.2"
    for _ in range(3):
        a.register_failure(ip)
    assert a.is_locked(ip)[0] is True
    a.clear(ip)
    assert a.is_locked(ip) == (False, 0)


def test_lockout_expires():
    a = _fresh_auth(GATE_MAX_TRIES="2", GATE_LOCKOUT_S="0")  # instant expiry
    ip = "10.0.0.3"
    a.clear(ip)
    a.register_failure(ip)
    a.register_failure(ip)
    time.sleep(0.01)
    assert a.is_locked(ip)[0] is False  # 0s lockout has elapsed


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")
