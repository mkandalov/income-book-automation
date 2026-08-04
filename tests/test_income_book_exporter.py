from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from income_book_automation.exporters.income_book import (
    IncomeBookExportError,
    MissingIncomeBookDateError,
    MissingIncomeBookSheetError,
    export_income_book,
)
from income_book_automation.models import DailyIncomeBookEntry


def _create_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2026"

    sheet["A6"] = date(2026, 6, 1)
    sheet["A6"].number_format = "m/d/yy"
    sheet["J6"] = "=K6+L6+M6"
    sheet["J7"] = "=SUM(J6:J6)"
    sheet["K6"].fill = PatternFill(fill_type="solid", fgColor="FFFF00")

    workbook.save(path)
    workbook.close()


def _entry(day: int = 1) -> DailyIncomeBookEntry:
    return DailyIncomeBookEntry(
        date=date(2026, 6, day),
        checkbox_card_income=Decimal("90.00"),
        checkbox_cash_income=Decimal("50.00"),
        bank_income=Decimal("20.00"),
    )


def test_export_income_book_updates_matching_date_and_preserves_template(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output" / "income-book.xlsx"
    _create_template(template_path)
    original_template = template_path.read_bytes()

    result = export_income_book(
        template_path,
        output_path,
        [_entry()],
        sheet_name="2026",
    )

    assert result == output_path
    assert template_path.read_bytes() == original_template

    workbook = load_workbook(output_path, data_only=False)
    try:
        sheet = workbook["2026"]
        assert sheet["K6"].value == 90
        assert sheet["L6"].value == 50
        assert sheet["M6"].value == 20
        assert sheet["J6"].value == "=K6+L6+M6"
        assert sheet["J7"].value == "=SUM(J6:J6)"
        assert sheet["K6"].fill.fgColor.rgb.endswith("FFFF00")
    finally:
        workbook.close()


def test_export_income_book_rejects_missing_date(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"
    _create_template(template_path)

    with pytest.raises(MissingIncomeBookDateError, match="2026-06-02"):
        export_income_book(
            template_path,
            output_path,
            [_entry(day=2)],
            sheet_name="2026",
        )

    assert not output_path.exists()


def test_export_income_book_rejects_missing_sheet(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"
    _create_template(template_path)

    with pytest.raises(MissingIncomeBookSheetError, match="missing-sheet"):
        export_income_book(
            template_path,
            output_path,
            [_entry()],
            sheet_name="missing-sheet",
        )

    assert not output_path.exists()


def test_export_income_book_refuses_to_overwrite_template(tmp_path: Path) -> None:
    template_path = tmp_path / "template.xlsx"
    _create_template(template_path)
    original_template = template_path.read_bytes()

    with pytest.raises(IncomeBookExportError, match="must differ"):
        export_income_book(
            template_path,
            template_path,
            [_entry()],
            sheet_name="2026",
        )

    assert template_path.read_bytes() == original_template
