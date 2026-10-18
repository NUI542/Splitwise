from pathlib import Path

import pytest

from metta_syntax import check_file

RULES = sorted((Path(__file__).resolve().parent.parent / "rules").glob("*.metta"))


@pytest.mark.parametrize("path", RULES, ids=[p.name for p in RULES])
def test_rule_file_brackets_balance(path):
    assert check_file(path)
