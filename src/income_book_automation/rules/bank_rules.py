"""Deterministic bank transaction classification rules."""

from enum import StrEnum

from income_book_automation.models import (
    BankName,
    BankTransaction,
    ClassifiedTransaction,
    ClientProfile,
    ReviewField,
    TransactionCategory,
)

EXCLUDED_PAYMENT_RULES = (
    ("повернення коштів", "refund payment"),
    ("Повернення", "refund"),
    ("гривні від продажу", "currency sale proceeds"),
)

LIQPAY_COUNTERPARTY_TAX_ID = "14360570"
BOLT_COUNTERPARTY_TAX_ID = "43637532"

SENSE_ACQUIRING_MARKERS = (
    "еквайрінг",
    "еквайринг",
)

RETURNABLE_STEMS = ("поворотн",)
FINANCIAL_STEMS = ("фінанс", "финанс")
ASSISTANCE_STEMS = ("допомог",)


class DuplicateSettlementProvider(StrEnum):
    LIQPAY = "liqpay"
    BOLT = "bolt"
    SENSE_ACQUIRING = "sense_acquiring"


def _normalize_account(value: str) -> str:
    return "".join(value.split()).upper()


def _normalize_tax_id(value: str | None) -> str:
    if value is None:
        return ""

    return "".join(character for character in value if character.isdigit())


def _normalize_text(value: str) -> str:
    value = value.casefold().replace("-", " ")
    return " ".join(value.split())


def _compact_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _contains_marker(value: str, marker: str) -> bool:
    return _compact_text(marker) in _compact_text(value)


def detect_duplicate_settlement(
    transaction: BankTransaction,
) -> DuplicateSettlementProvider | None:
    """Recognize verified settlements that duplicate Checkbox revenue."""
    if transaction.credit <= 0:
        return None

    counterparty_tax_id = _normalize_tax_id(transaction.counterparty_tax_id)

    if counterparty_tax_id == BOLT_COUNTERPARTY_TAX_ID:
        return DuplicateSettlementProvider.BOLT

    mentions_liqpay = _contains_marker(
        f"{transaction.counterparty} {transaction.payment_purpose}",
        "liqpay",
    )
    if counterparty_tax_id == LIQPAY_COUNTERPARTY_TAX_ID and mentions_liqpay:
        return DuplicateSettlementProvider.LIQPAY

    payment_purpose = _normalize_text(transaction.payment_purpose)
    if transaction.bank is BankName.SENSE and any(
        marker in payment_purpose for marker in SENSE_ACQUIRING_MARKERS
    ):
        return DuplicateSettlementProvider.SENSE_ACQUIRING

    return None


def _detect_unverified_settlement_marker(
    transaction: BankTransaction,
) -> DuplicateSettlementProvider | None:
    """Find provider text whose tax ID does not confirm the provider."""
    if transaction.credit <= 0:
        return None

    counterparty_tax_id = _normalize_tax_id(transaction.counterparty_tax_id)
    combined_text = f"{transaction.counterparty} {transaction.payment_purpose}"

    if (
        _contains_marker(combined_text, "liqpay")
        and counterparty_tax_id != LIQPAY_COUNTERPARTY_TAX_ID
    ):
        return DuplicateSettlementProvider.LIQPAY

    mentions_bolt = _contains_marker(transaction.counterparty, "болт") or (
        _contains_marker(transaction.payment_purpose, "boltfood")
    )
    if mentions_bolt and counterparty_tax_id != BOLT_COUNTERPARTY_TAX_ID:
        return DuplicateSettlementProvider.BOLT

    return None


def _is_within_one_typo(left: str, right: str) -> bool:
    """Compare words allowing one insertion, deletion, substitution or swap."""
    if left == right:
        return True

    if abs(len(left) - len(right)) > 1:
        return False

    if len(left) == len(right):
        differences = [
            index
            for index, (left_char, right_char) in enumerate(
                zip(left, right, strict=True)
            )
            if left_char != right_char
        ]
        if len(differences) <= 1:
            return True
        if len(differences) != 2:
            return False

        first, second = differences
        return (
            second == first + 1
            and left[first] == right[second]
            and left[second] == right[first]
        )

    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    shorter_index = 0
    longer_index = 0
    skipped_character = False

    while shorter_index < len(shorter) and longer_index < len(longer):
        if shorter[shorter_index] == longer[longer_index]:
            shorter_index += 1
            longer_index += 1
            continue

        if skipped_character:
            return False

        skipped_character = True
        longer_index += 1

    return True


def _token_matches_stem(token: str, stems: tuple[str, ...]) -> bool:
    for stem in stems:
        if token.startswith(stem):
            return True

        minimum_length = max(1, len(stem) - 1)
        maximum_length = min(len(token), len(stem) + 1)
        for prefix_length in range(minimum_length, maximum_length + 1):
            if _is_within_one_typo(token[:prefix_length], stem):
                return True

    return False


def _purpose_tokens(value: str) -> tuple[str, ...]:
    normalized = "".join(
        character if character.isalnum() else " " for character in value.casefold()
    )
    return tuple(normalized.split())


def is_returnable_financial_assistance(payment_purpose: str) -> bool:
    """Recognize common inflections and small typos in returnable assistance."""
    tokens = _purpose_tokens(payment_purpose)

    if any(token.startswith("безповоротн") for token in tokens):
        return False

    returnable_positions = [
        index
        for index, token in enumerate(tokens)
        if _token_matches_stem(token, RETURNABLE_STEMS)
        and not (index > 0 and tokens[index - 1] == "без")
    ]
    financial_positions = [
        index
        for index, token in enumerate(tokens)
        if _token_matches_stem(token, FINANCIAL_STEMS)
    ]
    assistance_positions = [
        index
        for index, token in enumerate(tokens)
        if _token_matches_stem(token, ASSISTANCE_STEMS)
    ]

    return any(
        returnable_index < financial_index < assistance_index
        and assistance_index - returnable_index <= 5
        for returnable_index in returnable_positions
        for financial_index in financial_positions
        for assistance_index in assistance_positions
    )


def _settlement_reason(provider: DuplicateSettlementProvider) -> str:
    return f"{provider.value} settlement covered by Checkbox"


def _find_missing_review_fields(
    transaction: BankTransaction,
) -> frozenset[ReviewField]:
    missing_fields: set[ReviewField] = set()

    if not transaction.document_number.strip():
        missing_fields.add(ReviewField.DOCUMENT_NUMBER)

    if not _normalize_text(transaction.counterparty):
        missing_fields.add(ReviewField.COUNTERPARTY)

    if not _normalize_account(transaction.counterparty_account):
        missing_fields.add(ReviewField.COUNTERPARTY_ACCOUNT)

    if not _normalize_tax_id(transaction.counterparty_tax_id):
        missing_fields.add(ReviewField.COUNTERPARTY_TAX_ID)

    if not _normalize_text(transaction.payment_purpose):
        missing_fields.add(ReviewField.PAYMENT_PURPOSE)

    return frozenset(missing_fields)


def classify_bank_transaction(
    transaction: BankTransaction,
    client: ClientProfile,
    *,
    checkbox_included: bool = False,
) -> ClassifiedTransaction:
    if transaction.debit > 0:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.EXCLUDED,
            reason="debit transaction",
        )

    settlement_provider = detect_duplicate_settlement(transaction)
    if checkbox_included and settlement_provider is not None:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.EXCLUDED,
            reason=_settlement_reason(settlement_provider),
        )

    missing_fields = _find_missing_review_fields(transaction)

    if missing_fields:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.NEEDS_REVIEW,
            reason="required review fields are missing",
            missing_fields=missing_fields,
        )

    if _detect_unverified_settlement_marker(transaction) is not None:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.NEEDS_REVIEW,
            reason="settlement provider identity requires review",
        )

    counterparty_account = _normalize_account(transaction.counterparty_account)
    client_accounts = {_normalize_account(account) for account in client.own_accounts}
    account_matches = counterparty_account in client_accounts

    counterparty_tax_id = _normalize_tax_id(transaction.counterparty_tax_id)
    client_tax_id = _normalize_tax_id(client.tax_id)
    tax_id_matches = counterparty_tax_id == client_tax_id

    client_names = {
        _normalize_text(name)
        for name in (client.legal_name, *client.name_aliases)
        if name.strip()
    }
    counterparty_name = _normalize_text(transaction.counterparty)
    name_matches = counterparty_name in client_names

    has_foreign_tax_id = bool(
        counterparty_tax_id and client_tax_id and not tax_id_matches
    )

    if has_foreign_tax_id and (account_matches or name_matches):
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.NEEDS_REVIEW,
            reason="counterparty identity conflicts with client profile",
        )

    if account_matches:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty account belongs to client",
        )

    if tax_id_matches:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty tax ID belongs to client",
        )

    if name_matches:
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.OWN_TRANSFER,
            reason="counterparty name belongs to client",
        )

    payment_purpose = _normalize_text(transaction.payment_purpose)

    if is_returnable_financial_assistance(transaction.payment_purpose):
        return ClassifiedTransaction(
            transaction=transaction,
            category=TransactionCategory.EXCLUDED,
            reason="returnable financial assistance",
        )

    for pattern, reason in EXCLUDED_PAYMENT_RULES:
        if _normalize_text(pattern) in payment_purpose:
            return ClassifiedTransaction(
                transaction=transaction,
                category=TransactionCategory.EXCLUDED,
                reason=reason,
            )

    return ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.INCOME,
        reason="eligible incoming payment",
    )
