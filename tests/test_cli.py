from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from typer.testing import CliRunner

from income_book_automation.cli import app

COLUMN_COUNT = 29
runner = CliRunner()


def test_checkbox_summary_prints_aggregated_totals(tmp_path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    headers: list[object] = [None] * COLUMN_COUNT
    headers[1] = "Дата відкриття"
    headers[25] = "Виручка безготівка"
    headers[26] = "Повернення безготівка"
    headers[27] = "Виручка готівка"
    headers[28] = "Повернення готівка"
    worksheet.append(headers)

    row: list[object] = [None] * COLUMN_COUNT
    # Excel stores timestamps without timezone information.
    row[1] = datetime(2026, 6, 18, 8, 49)  # noqa: DTZ001
    row[25] = 37331
    row[26] = 844
    row[27] = 1000
    row[28] = 100
    worksheet.append(row)

    source_path = tmp_path / "checkbox.xlsx"
    workbook.save(source_path)
    workbook.close()

    result = runner.invoke(app, ["checkbox-summary", str(source_path)])

    assert result.exit_code == 0
    assert "Days: 1" in result.stdout
    assert "Card revenue: 36,487.00" in result.stdout
    assert "Cash revenue: 900.00" in result.stdout
    assert "Total revenue: 37,387.00" in result.stdout
