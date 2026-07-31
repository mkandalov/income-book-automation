from datetime import date
from decimal import Decimal

from income_book_automation.models import DailyCheckboxRevenue


def test_calculates_daily_net_revenue() -> None:
    record = DailyCheckboxRevenue(
        date=date(2026, 6, 18),
        card_revenue=Decimal("37331.00"),
        card_refund=Decimal("844.00"),
        cash_revenue=Decimal("0.00"),
        cash_refund=Decimal("0.00"),
    )

    assert record.card_net == Decimal("36487.00")
    assert record.cash_net == Decimal("0.00")
    assert record.total_net == Decimal("36487.00")
