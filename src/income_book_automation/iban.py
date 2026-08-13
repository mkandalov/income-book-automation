"""Validation helpers for Ukrainian IBAN account numbers."""

import re

UKRAINIAN_IBAN_PATTERN = re.compile(r"UA[0-9]{27}")


class InvalidUkrainianIbanError(ValueError):
    """Raised when a value is not a valid Ukrainian IBAN."""


def normalize_ukrainian_iban(value: str) -> str:
    """Normalize whitespace and validate format and ISO 13616 checksum."""
    normalized = "".join(value.split()).upper()

    if UKRAINIAN_IBAN_PATTERN.fullmatch(normalized) is None:
        raise InvalidUkrainianIbanError(
            "Ukrainian IBAN must contain UA followed by 27 digits"
        )

    rearranged = normalized[4:] + normalized[:4]
    remainder = 0

    for character in rearranged:
        numeric_part = character if character.isdigit() else str(ord(character) - 55)

        for digit in numeric_part:
            remainder = (remainder * 10 + int(digit)) % 97

    if remainder != 1:
        raise InvalidUkrainianIbanError("Ukrainian IBAN checksum is invalid")

    return normalized


def normalize_account_identifier(value: str) -> str:
    """Normalize a bank account identifier and validate it when it is an IBAN."""
    normalized = "".join(value.split()).upper()

    if normalized.startswith("UA"):
        return normalize_ukrainian_iban(normalized)

    return normalized
