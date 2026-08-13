import pytest

from income_book_automation.iban import (
    InvalidUkrainianIbanError,
    normalize_account_identifier,
    normalize_ukrainian_iban,
)

VALID_IBAN = "UA273000010000000000000000001"


def test_normalize_ukrainian_iban_removes_spaces_and_normalizes_case() -> None:
    result = normalize_ukrainian_iban(" ua27 300001 0000000000000000001 ")

    assert result == VALID_IBAN


@pytest.mark.parametrize(
    "value",
    [
        "UA1234567890",
        "PL273000010000000000000000001",
        "UA27ABC001000000000000000001",
    ],
)
def test_normalize_ukrainian_iban_rejects_invalid_format(value: str) -> None:
    with pytest.raises(
        InvalidUkrainianIbanError,
        match="UA followed by 27 digits",
    ):
        normalize_ukrainian_iban(value)


def test_normalize_ukrainian_iban_rejects_invalid_checksum() -> None:
    with pytest.raises(InvalidUkrainianIbanError, match="checksum"):
        normalize_ukrainian_iban("UA003000010000000000000000001")


def test_normalize_account_identifier_accepts_non_iban_bank_account() -> None:
    assert normalize_account_identifier(" 2600 1234567890 ") == "26001234567890"


def test_normalize_account_identifier_validates_iban_values() -> None:
    with pytest.raises(InvalidUkrainianIbanError, match="checksum"):
        normalize_account_identifier("UA003000010000000000000000001")
