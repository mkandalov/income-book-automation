"""Income classification rules."""

from datetime import date

from income_book_automation.models import DailyCheckboxRevenue


def aggregate_checkbox_by_date(
    records: list[DailyCheckboxRevenue],
) -> list[DailyCheckboxRevenue]:
    records_by_date: dict[date, DailyCheckboxRevenue] = {}

    for record in records:
        existing_record = records_by_date.get(record.date)

        if existing_record is None:
            records_by_date[record.date] = record.model_copy()
        else:
            existing_record.card_revenue += record.card_revenue
            existing_record.card_refund += record.card_refund
            existing_record.cash_revenue += record.cash_revenue
            existing_record.cash_refund += record.cash_refund

    return sorted(records_by_date.values(), key=lambda record: record.date)
