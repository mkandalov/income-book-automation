from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from income_book_automation.parsers.checkbox import (
    parse_checkbox_file,
    parse_checkbox_row,
)

COLUMN_COUNT = 29


def _excel_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
) -> datetime:
    # Excel stores timestamps without timezone information.
    return datetime(year, month, day, hour, minute)  # noqa: DTZ001


def _make_checkbox_row(
    opened_at: datetime,
    *,
    card_revenue: int | None,
    card_refund: int | None,
    cash_revenue: int | None,
    cash_refund: int | None,
) -> tuple[object, ...]:
    row: list[object] = [None] * COLUMN_COUNT
    row[1] = opened_at
    row[25] = card_revenue
    row[26] = card_refund
    row[27] = cash_revenue
    row[28] = cash_refund
    return tuple(row)


def test_parse_checkbox_row_maps_values_and_calculates_net() -> None:
    row = _make_checkbox_row(
        _excel_datetime(2026, 6, 18, 8, 49),
        card_revenue=37331,
        card_refund=844,
        cash_revenue=1000,
        cash_refund=100,
    )

    record = parse_checkbox_row(row)

    assert record.date == date(2026, 6, 18)
    assert record.card_net == Decimal(36487)
    assert record.cash_net == Decimal(900)
    assert record.total_net == Decimal(37387)


def test_parse_checkbox_row_converts_empty_amounts_to_zero() -> None:
    row = _make_checkbox_row(
        _excel_datetime(2026, 6, 19, 9, 0),
        card_revenue=None,
        card_refund=None,
        cash_revenue=None,
        cash_refund=None,
    )

    record = parse_checkbox_row(row)

    assert record.card_revenue == Decimal(0)
    assert record.card_refund == Decimal(0)
    assert record.cash_revenue == Decimal(0)
    assert record.cash_refund == Decimal(0)
    assert record.total_net == Decimal(0)


def test_parse_checkbox_file_reads_rows_and_skips_empty_date(
    tmp_path: Path,
) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([f"column_{index}" for index in range(COLUMN_COUNT)])
    worksheet.append(
        list(
            _make_checkbox_row(
                _excel_datetime(2026, 6, 1, 8, 0),
                card_revenue=1000,
                card_refund=100,
                cash_revenue=200,
                cash_refund=50,
            )
        )
    )
    worksheet.append([None] * COLUMN_COUNT)
    worksheet.append(
        list(
            _make_checkbox_row(
                _excel_datetime(2026, 6, 2, 8, 0),
                card_revenue=2000,
                card_refund=0,
                cash_revenue=300,
                cash_refund=0,
            )
        )
    )

    source_path = tmp_path / "checkbox.xlsx"
    workbook.save(source_path)
    workbook.close()

    records = parse_checkbox_file(source_path)

    assert len(records) == 2
    assert records[0].date == date(2026, 6, 1)
    assert records[0].total_net == Decimal(1050)
    assert records[1].date == date(2026, 6, 2)
    assert records[1].total_net == Decimal(2300)
