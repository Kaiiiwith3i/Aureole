import pytest

from core.compare import compare_field, normalize


@pytest.mark.parametrize("a,b", [
    ("MARIA  CLARA", "maria clara"),
    ("Santos , Maria", "santos,maria"),
    ("Ｍａｒｉａ １２３", "maria 123"),
    ("Peñaflor", "Penaflor"),
    ("2022 - 00123", "2022-00123"),
])
def test_normalize_text(a, b):
    assert normalize(a) == normalize(b)


def test_numeric_confusions():
    assert normalize("2O22-OO123") != normalize("2022-00123")
    assert normalize("2O22-OO123", True) == normalize("2022-00123", True)
    assert normalize("l.25", True) == normalize("I.25", True) == "1.25"
    assert normalize("2 0 2 2", True) == "2022"
    assert normalize("S8B", True) == "588"


def test_decisions():
    assert compare_field("2022-00123", "2O22-OO123", 0.95, numeric=True).status == "MATCH"
    assert compare_field("2022-00123", "2O22-OO123", 0.95).status != "MATCH"
    assert compare_field("1.25", "1.75", 0.99, numeric=True).status == "MISMATCH"
    assert compare_field("Maria Clara D. Santos", "Maria Clara D Santos", 0.95).status == "MATCH"
    assert compare_field("BS Computer Science", "BS Nursing", 0.99).status == "MISMATCH"
    assert compare_field("BS Computer Science", "BS Nursing", 0.5).status == "UNREADABLE"
    assert compare_field("1.25", "1.75", 0.5, numeric=True).status == "UNREADABLE"
    assert compare_field("BS Computer Science", "", 0.99).status == "UNREADABLE"
    assert compare_field("BS Computer Science", "bs computer science", 0.3).status == "MATCH"
