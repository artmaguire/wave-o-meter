"""Run all (offline, deterministic) test suites with plain python3.

    python3 tests/run_all.py

Excludes test_pipeline_live.py, which hits the network and is a manual check.
Works without pytest; each suite also exposes pytest-style test_* functions.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SUITES = ["tests.test_scoring", "tests.test_auth", "tests.test_engine",
          "tests.test_security_helpers"]


def main() -> int:
    total = passed = 0
    failures = []
    for mod_name in SUITES:
        mod = importlib.import_module(mod_name)
        fns = [v for k, v in sorted(vars(mod).items())
               if k.startswith("test_") and callable(v)]
        for fn in fns:
            total += 1
            try:
                fn()
                passed += 1
            except Exception as e:  # noqa: BLE001
                failures.append(f"{mod_name}.{fn.__name__}: {e}")
        print(f"{mod_name}: {len(fns)} tests")
    print(f"\n{passed}/{total} passed")
    for f in failures:
        print("FAIL", f)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
