"""Exporter for the income-book Excel workbook."""

from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from income_book_automation.models import DailyIncomeBookEntry

DATE_COLUMN = 1
CARD_INCOME_COLUMN = 11
CASH_INCOME_COLUMN = 12
BANK_INCOME_COLUMN = 13


class IncomeBookExportError(Exception):
    """Base error raised while exporting an income book."""


class MissingIncomeBookSheetError(IncomeBookExportError):
    """Raised when the requested worksheet does not exist."""


class MissingIncomeBookDateError(IncomeBookExportError):
    """Raised when an entry date is absent from the template."""


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return None


def _index_rows_by_date(sheet: Worksheet) -> dict[date, int]:
    rows_by_date: dict[date, int] = {}

    for row_number in range(1, sheet.max_row + 1):
        transaction_date = _as_date(
            sheet.cell(
                row=row_number,
                column=DATE_COLUMN,
            ).value
        )

        if transaction_date is not None:
            rows_by_date[transaction_date] = row_number

    return rows_by_date


def export_income_book(
    template_path: Path,
    output_path: Path,
    entries: list[DailyIncomeBookEntry],
    *,
    sheet_name: str,
) -> Path:
    if template_path.resolve() == output_path.resolve():
        raise IncomeBookExportError("output path must differ from template path")

    workbook = load_workbook(
        template_path,
        data_only=False,
    )

    try:
        if sheet_name not in workbook.sheetnames:
            raise MissingIncomeBookSheetError(
                f"income-book sheet not found: {sheet_name}"
            )

        sheet = workbook[sheet_name]
        rows_by_date = _index_rows_by_date(sheet)

        missing_dates = sorted(
            entry.date for entry in entries if entry.date not in rows_by_date
        )

        if missing_dates:
            formatted_dates = ", ".join(
                missing_date.isoformat() for missing_date in missing_dates
            )
            raise MissingIncomeBookDateError(
                f"income-book dates not found: {formatted_dates}"
            )

        for entry in entries:
            row_number = rows_by_date[entry.date]

            sheet.cell(
                row=row_number,
                column=CARD_INCOME_COLUMN,
            ).value = entry.checkbox_card_income

            sheet.cell(
                row=row_number,
                column=CASH_INCOME_COLUMN,
            ).value = entry.checkbox_cash_income

            sheet.cell(
                row=row_number,
                column=BANK_INCOME_COLUMN,
            ).value = entry.bank_income

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        workbook.save(output_path)

    finally:
        workbook.close()

    return output_path
