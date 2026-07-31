"""Domain models used by the income-book automation application."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field


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
