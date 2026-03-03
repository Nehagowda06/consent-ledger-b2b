from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
RED_TEAM_DIR = TESTS_DIR / "red_team"


def _run_suite(name: str, suite: unittest.TestSuite) -> bool:
    print(f"\n=== {name} ===")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def main() -> int:
    loader = unittest.defaultTestLoader
    existing_suite = loader.discover(
        start_dir=str(TESTS_DIR),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )
    if not _run_suite("Existing Test Suite", existing_suite):
        return 1

    if RED_TEAM_DIR.exists():
        red_team_suite = loader.discover(
            start_dir=str(RED_TEAM_DIR),
            pattern="rt_*.py",
            top_level_dir=str(TESTS_DIR),
        )
        if not _run_suite("Red-Team Adversarial Suite", red_team_suite):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
