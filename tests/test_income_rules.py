from datetime import date
from decimal import Decimal

from income_book_automation.models import DailyCheckboxRevenue
from income_book_automation.rules.income_rules import aggregate_checkbox_by_date


def _record(
    day: int,
    *,
    card_revenue: int,
    card_refund: int,
    cash_revenue: int,
    cash_refund: int,
) -> DailyCheckboxRevenue:
    return DailyCheckboxRevenue(
        date=date(2026, 6, day),
        card_revenue=Decimal(card_revenue),
        card_refund=Decimal(card_refund),
        cash_revenue=Decimal(cash_revenue),
        cash_refund=Decimal(cash_refund),
    )


def test_aggregate_checkbox_by_date_groups_and_sorts_records() -> None:
    first_record = _record(
        1,
        card_revenue=1000,
        card_refund=100,
        cash_revenue=200,
        cash_refund=20,
    )
    records = [
        _record(
            2,
            card_revenue=2000,
            card_refund=0,
            cash_revenue=0,
            cash_refund=0,
        ),
        first_record,
        _record(
            1,
            card_revenue=500,
            card_refund=50,
            cash_revenue=300,
            cash_refund=30,
        ),
    ]

    result = aggregate_checkbox_by_date(records)

    assert [record.date for record in result] == [
        date(2026, 6, 1),
        date(2026, 6, 2),
    ]
    assert result[0].card_revenue == Decimal(1500)
    assert result[0].card_refund == Decimal(150)
    assert result[0].cash_revenue == Decimal(500)
    assert result[0].cash_refund == Decimal(50)
    assert result[0].card_net == Decimal(1350)
    assert result[0].cash_net == Decimal(450)
    assert result[0].total_net == Decimal(1800)
    assert first_record.card_revenue == Decimal(1000)


def test_aggregate_checkbox_by_date_accepts_empty_list() -> None:
    assert aggregate_checkbox_by_date([]) == []
