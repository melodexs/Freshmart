import pytest

from app.phone import normalise


@pytest.mark.parametrize(
    "raw",
    [
        "08012345678",
        "0801 234 5678",
        "+234 801 234 5678",
        "2348012345678",
        "801-234-5678",
        "(0801) 234-5678",
    ],
)
def test_common_ways_of_typing_a_number_normalise_to_local_form(raw):
    assert normalise(raw) == "08012345678"


@pytest.mark.parametrize(
    "raw", ["", "123", "0801234567", "080123456789", "05012345678", "abcdefghijk", None]
)
def test_invalid_numbers_are_rejected(raw):
    assert normalise(raw) is None
