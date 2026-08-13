"""Domain models used by the income-book automation application."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from income_book_automation.iban import (
    normalize_account_identifier,
    normalize_ukrainian_iban,
)


class DailyCheckboxRevenue(BaseModel):
    date: date
    card_revenue: Decimal = Field(ge=Decimal(0), decimal_places=2)
    card_refund: Decimal = Field(ge=Decimal(0), decimal_places=2)
    cash_revenue: Decimal = Field(ge=Decimal(0), decimal_places=2)
    cash_refund: Decimal = Field(ge=Decimal(0), decimal_places=2)

    @computed_field
    @property
    def card_net(self) -> Decimal:
        return self.card_revenue - self.card_refund

    @computed_field
    @property
    def cash_net(self) -> Decimal:
        return self.cash_revenue - self.cash_refund

    @computed_field
    @property
    def total_net(self) -> Decimal:
        return self.card_net + self.cash_net


class CheckboxPaymentMethod(StrEnum):
    CARD = "card"
    CASH = "cash"


class CheckboxRefundWarning(BaseModel):
    date: date
    payment_method: CheckboxPaymentMethod

    revenue: Decimal = Field(
        ge=Decimal("0.00"),
        decimal_places=2,
    )
    refund: Decimal = Field(
        ge=Decimal("0.00"),
        decimal_places=2,
    )

    @computed_field
    @property
    def result(self) -> Decimal:
        return self.revenue - self.refund


class DailyBankIncome(BaseModel):
    date: date
    amount: Decimal = Field(ge=Decimal("0.00"), decimal_places=2)


class DailyIncomeBookEntry(BaseModel):
    date: date

    checkbox_card_income: Decimal = Field(decimal_places=2)
    checkbox_cash_income: Decimal = Field(decimal_places=2)
    bank_income: Decimal = Field(
        ge=Decimal("0.00"),
        decimal_places=2,
    )

    @computed_field
    @property
    def total_income(self) -> Decimal:
        return self.checkbox_card_income + self.checkbox_cash_income + self.bank_income


class BankName(StrEnum):
    PUMB = "pumb"
    PRIVAT = "privat"
    MONO = "mono"
    ABANK = "abank"


class TransactionSource(BaseModel):
    original_filename: str
    row_number: int = Field(ge=1)

    @field_validator("original_filename")
    @classmethod
    def validate_original_filename(cls, value: str) -> str:
        filename = value.strip()

        if not filename:
            raise ValueError("original filename must not be blank")

        return filename


class TransactionCategory(StrEnum):
    INCOME = "income"
    OWN_TRANSFER = "own_transfer"
    EXCLUDED = "excluded"
    NEEDS_REVIEW = "needs_review"


class ReviewField(StrEnum):
    DOCUMENT_NUMBER = "document_number"
    COUNTERPARTY = "counterparty"
    COUNTERPARTY_ACCOUNT = "counterparty_account"
    COUNTERPARTY_TAX_ID = "counterparty_tax_id"
    PAYMENT_PURPOSE = "payment_purpose"


class ClientProfile(BaseModel):
    client_id: str
    legal_name: str
    tax_id: str

    own_accounts: frozenset[str] = Field(default_factory=frozenset)

    name_aliases: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("own_accounts")
    @classmethod
    def validate_own_accounts(cls, values: frozenset[str]) -> frozenset[str]:
        return frozenset(normalize_ukrainian_iban(value) for value in values)


class BankTransaction(BaseModel):
    source: TransactionSource

    date: date
    bank: BankName
    account_number: str
    currency: str

    document_number: str

    debit: Decimal = Field(ge=Decimal(0), decimal_places=2)
    credit: Decimal = Field(ge=Decimal(0), decimal_places=2)

    counterparty: str
    counterparty_account: str
    payment_purpose: str

    counterparty_tax_id: str | None = None

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, value: str) -> str:
        return normalize_ukrainian_iban(value)

    @field_validator("counterparty_account")
    @classmethod
    def validate_counterparty_account(cls, value: str) -> str:
        if not value.strip():
            return ""

        return normalize_account_identifier(value)

    @model_validator(mode="after")
    def validate_direction(self) -> Self:
        has_debit = self.debit > 0
        has_credit = self.credit > 0

        if has_credit == has_debit:
            raise ValueError("exactly one of debit or credit must be positive")

        return self


class ClassifiedTransaction(BaseModel):
    transaction: BankTransaction
    category: TransactionCategory
    reason: str

    missing_fields: frozenset[ReviewField] = Field(default_factory=frozenset)
