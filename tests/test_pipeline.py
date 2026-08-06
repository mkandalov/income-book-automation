import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from income_book_automation.models import (
    BankName,
    ClientProfile,
    TransactionCategory,
)
from income_book_automation.pipeline import (
    MissingStatementAccountError,
    run_income_book_pipeline,
)


def _write_pumb_statement(path: Path) -> None:
    rows = [
        [
            "ST_DATE",
            "ACC_NUMB",
            "CUR_NUMB",
            "DOC_NO",
            "DB",
            "CR",
            "KOR_NAME",
            "KOR_ACC",
            "KOR_OKPO",
            "DESCRIPT",
        ],
        [
            "2026.06.01",
            "UA000000000000000000000000001",
            "980",
            "TEST-001",
            "0",
            "20.00",
            "ТОВ Тестовий покупець",
            "UA000000000000000000000000010",
            "11111111",
            "Оплата за тестові послуги",
        ],
        [
            "2026.06.01",
            "UA000000000000000000000000001",
            "980",
            "TEST-002",
            "0",
            "30.00",
            "ФОП Тестовий Тарас Іванович",
            "UA000000000000000000000000002",
            "0000000000",
            "Переказ між власними рахунками",
        ],
        [
            "2026.06.01",
            "UA000000000000000000000000001",
            "980",
            "TEST-003",
            "0",
            "40.00",
            "",
            "",
            "",
            "",
        ],
    ]

    with path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerows(rows)


def _write_checkbox_report(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Дата відкриття",
            "Виручка безготівка",
            "Повернення безготівка",
            "Виручка готівка",
            "Повернення готівка",
        ]
    )
    sheet.append(
        [
            # Excel stores timestamps without timezone information.
            datetime(2026, 6, 1, 12, 0),  # noqa: DTZ001
            100,
            10,
            50,
            0,
        ]
    )
    workbook.save(path)
    workbook.close()


def _write_income_book_template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2026"
    sheet["A6"] = date(2026, 6, 1)
    sheet["A6"].number_format = "yyyy-mm-dd"
    workbook.save(path)
    workbook.close()


def _client_profile() -> ClientProfile:
    return ClientProfile(
        client_id="client-001",
        legal_name="ФОП Тестовий Тарас Іванович",
        tax_id="0000000000",
        own_accounts={
            "UA000000000000000000000000001",
            "UA000000000000000000000000002",
        },
    )


def test_run_income_book_pipeline_processes_sources_and_exports_workbook(
    tmp_path: Path,
) -> None:
    statement_path = tmp_path / "statement.csv"
    checkbox_path = tmp_path / "checkbox.xlsx"
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"

    _write_pumb_statement(statement_path)
    _write_checkbox_report(checkbox_path)
    _write_income_book_template(template_path)

    result = run_income_book_pipeline(
        client=_client_profile(),
        bank=BankName.PUMB,
        bank_statement_path=statement_path,
        checkbox_path=checkbox_path,
        template_path=template_path,
        output_path=output_path,
        sheet_name="2026",
    )

    assert result.output_path == output_path
    assert len(result.daily_entries) == 1
    assert result.daily_entries[0].date == date(2026, 6, 1)
    assert result.daily_entries[0].checkbox_card_income == Decimal("90.00")
    assert result.daily_entries[0].checkbox_cash_income == Decimal("50.00")
    assert result.daily_entries[0].bank_income == Decimal("20.00")

    assert [record.category for record in result.classified_transactions] == [
        TransactionCategory.INCOME,
        TransactionCategory.OWN_TRANSFER,
        TransactionCategory.NEEDS_REVIEW,
    ]
    assert result.needs_review == (result.classified_transactions[2],)

    workbook = load_workbook(output_path, data_only=False)
    try:
        sheet = workbook["2026"]
        assert sheet["B6"].value == 160
        assert sheet["K6"].value == 90
        assert sheet["L6"].value == 50
        assert sheet["M6"].value == 20
    finally:
        workbook.close()


def test_run_income_book_pipeline_requires_statement_account_for_mono(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        MissingStatementAccountError,
        match="Mono statement account is required",
    ):
        run_income_book_pipeline(
            client=_client_profile(),
            bank=BankName.MONO,
            bank_statement_path=tmp_path / "statement.csv",
            checkbox_path=tmp_path / "checkbox.xlsx",
            template_path=tmp_path / "template.xlsx",
            output_path=tmp_path / "output.xlsx",
            sheet_name="2026",
        )
