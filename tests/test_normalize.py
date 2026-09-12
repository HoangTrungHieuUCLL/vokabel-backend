import pytest

from app.normalize import make_search_key


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("üben", "ueben"),
        ("die Straße", "strasse"),
        ("sich erinnern", "erinnern"),
        ("sich zu erinnern", "erinnern"),
        ("Entschuldigung!", "entschuldigung"),
        ("an|rufen", "anrufen"),
    ],
)
def test_make_search_key(word: str, expected: str) -> None:
    assert make_search_key(word) == expected
