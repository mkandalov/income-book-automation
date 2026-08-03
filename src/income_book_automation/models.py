"""Domain models used by the income-book automation application."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, computed_field, model_validator


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


class BankName(StrEnum):
    PUMB = "pumb"
    PRIVAT = "privat"
    MONO = "mono"


class BankTransaction(BaseModel):
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

    @model_validator(mode="after")
    def validate_direction(self) -> Self:
        has_debit = self.debit > 0
        has_credit = self.credit > 0

        if has_credit == has_debit:
            raise ValueError("exactly one of debit or credit must be positive")

        return self
