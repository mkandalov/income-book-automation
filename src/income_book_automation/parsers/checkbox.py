"""Parser for Checkbox Z-report workbooks."""

from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from income_book_automation.models import DailyCheckboxRevenue

DATE_INDEX = 1
CARD_REVENUE_INDEX = 25
CARD_REFUND_INDEX = 26
CASH_REVENUE_INDEX = 27
CASH_REFUND_INDEX = 28


def parse_checkbox_row(row: tuple[object, ...]) -> DailyCheckboxRevenue:
    opened_at = row[DATE_INDEX]
    opened_date = opened_at.date()

    card_revenue = Decimal(str(row[CARD_REVENUE_INDEX] or 0))

    card_refund = Decimal(str(row[CARD_REFUND_INDEX] or 0))

    cash_revenue = Decimal(str(row[CASH_REVENUE_INDEX] or 0))

    cash_refund = Decimal(str(row[CASH_REFUND_INDEX] or 0))

    return DailyCheckboxRevenue(
        date=opened_date,
        card_revenue=card_revenue,
        card_refund=card_refund,
        cash_revenue=cash_revenue,
        cash_refund=cash_refund,
    )


def parse_checkbox_file(path: Path) -> list[DailyCheckboxRevenue]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook.active

    records = []

    for row in worksheet.iter_rows(min_row=2, values_only=True):
        if row[DATE_INDEX] is None:
            continue

        record = parse_checkbox_row(row)
        records.append(record)

    workbook.close()

    return records
