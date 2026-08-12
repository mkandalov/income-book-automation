from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from income_book_automation.exporters.income_book import (
    HelperColumnMapping,
    IncomeBookExportError,
    InvalidHelperColumnMappingError,
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


def _create_book_through_may(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2026"

    sheet["A6"] = date(2026, 4, 1)
    sheet["B6"] = 10
    sheet["D6"] = "=B6-C6"
    sheet["F6"] = "=D6+E6"
    sheet["J6"] = "=K6+L6+M6"
    sheet["A7"] = "Всього квітень:"
    sheet["B7"] = "=SUM(B6:B6)"

    sheet["A8"] = date(2026, 5, 1)
    sheet["B8"] = 20
    sheet["D8"] = "=B8-C8"
    sheet["F8"] = "=D8+E8"
    sheet["J8"] = "=K8+L8+M8"
    sheet["A9"] = "Всього травень:"
    sheet["B9"] = "=SUM(B8:B8)"

    sheet["A10"] = "Всього 2026 рік:"
    sheet["B10"] = "=B7+B9"

    sheet["A8"].number_format = "m/d/yy"
    sheet["K8"].fill = PatternFill(fill_type="solid", fgColor="D9EAD3")
    sheet["A9"].fill = PatternFill(fill_type="solid", fgColor="FFFF00")

    workbook.save(path)
    workbook.close()


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
        assert sheet["A6"].value.date() == date(2026, 6, 1)
        assert sheet["B6"].value == 160
        assert sheet["C6"].value == 0
        assert sheet["D6"].value == "=B6-C6"
        assert sheet["E6"].value == 0
        assert sheet["F6"].value == "=D6+E6"
        assert sheet["G6"].value == 0
        assert sheet["H6"].value == 0
        assert sheet["K6"].value == 90
        assert sheet["L6"].value == 50
        assert sheet["M6"].value == 20
        assert sheet["J6"].value == "=K6+L6+M6"
        assert sheet["J7"].value == "=SUM(J6:J6)"
        assert sheet["K6"].fill.fgColor.rgb.endswith("FFFF00")
    finally:
        workbook.close()


def test_export_income_book_supports_custom_helper_columns(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"
    _create_template(template_path)

    helper_columns = HelperColumnMapping(
        total=10,
        checkbox_card=12,
        checkbox_cash=13,
        bank_income=14,
    )

    export_income_book(
        template_path,
        output_path,
        [_entry()],
        sheet_name="2026",
        helper_columns=helper_columns,
    )

    workbook = load_workbook(output_path, data_only=False)
    try:
        sheet = workbook["2026"]

        assert sheet["J6"].value == "=L6+M6+N6"
        assert sheet["K6"].value is None
        assert sheet["L6"].value == 90
        assert sheet["M6"].value == 50
        assert sheet["N6"].value == 20
    finally:
        workbook.close()


def test_helper_column_mapping_rejects_duplicate_columns() -> None:
    with pytest.raises(
        InvalidHelperColumnMappingError,
        match="must be unique",
    ):
        HelperColumnMapping(
            total=10,
            checkbox_card=11,
            checkbox_cash=11,
            bank_income=13,
        )


def test_helper_column_mapping_rejects_official_columns() -> None:
    with pytest.raises(
        InvalidHelperColumnMappingError,
        match="must start from column 10",
    ):
        HelperColumnMapping(
            total=9,
            checkbox_card=11,
            checkbox_cash=12,
            bank_income=13,
        )


def test_helper_column_mapping_rejects_columns_after_fifteen() -> None:
    with pytest.raises(
        InvalidHelperColumnMappingError,
        match="must not exceed column 15",
    ):
        HelperColumnMapping(
            total=10,
            checkbox_card=11,
            checkbox_cash=12,
            bank_income=16,
        )


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


def test_export_income_book_appends_new_month_and_period_totals(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"
    _create_book_through_may(template_path)

    export_income_book(
        template_path,
        output_path,
        [_entry(day=3), _entry(day=1)],
        sheet_name="2026",
    )

    workbook = load_workbook(output_path, data_only=False)
    try:
        sheet = workbook["2026"]

        assert sheet["A10"].value.date() == date(2026, 6, 1)
        assert sheet["A11"].value.date() == date(2026, 6, 3)
        assert sheet["B10"].value == 160
        assert sheet["B11"].value == 160
        assert sheet["D10"].value == "=B10-C10"
        assert sheet["F10"].value == "=D10+E10"
        assert sheet["J10"].value == "=K10+L10+M10"
        assert sheet["K10"].fill.fgColor.rgb.endswith("D9EAD3")

        assert sheet["A12"].value == "Всього червень:"
        assert sheet["B12"].value == "=SUM(B10:B11)"
        assert sheet["D12"].value == "=B12-C12"
        assert sheet["F12"].value == "=D12+E12"
        assert sheet["A12"].fill.fgColor.rgb.endswith("FFFF00")

        assert sheet["A13"].value == "Всього 2 кв 2026:"
        assert sheet["B13"].value == "=B7+B9+B12"

        assert sheet["A14"].value == "Всього 1 півріччя 2026:"
        assert sheet["B14"].value == "=B7+B9+B12"

        assert sheet["A15"].value == "Всього 2026 рік:"
        assert sheet["B15"].value == "=B7+B9+B12"
    finally:
        workbook.close()


def test_export_income_book_rejects_entries_from_multiple_months(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"
    _create_book_through_may(template_path)

    entries = [
        _entry(day=1),
        DailyIncomeBookEntry(
            date=date(2026, 7, 1),
            checkbox_card_income=Decimal("10.00"),
            checkbox_cash_income=Decimal("0.00"),
            bank_income=Decimal("0.00"),
        ),
    ]

    with pytest.raises(IncomeBookExportError, match="one calendar month"):
        export_income_book(
            template_path,
            output_path,
            entries,
            sheet_name="2026",
        )

    assert not output_path.exists()
