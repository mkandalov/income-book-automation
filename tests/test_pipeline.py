import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from income_book_automation.models import (
    BankName,
    BankTransaction,
    ClientProfile,
    TransactionCategory,
)
from income_book_automation.pipeline import (
    BankStatementSource,
    IncomeBookPipelineError,
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


def _write_overlapping_pumb_statement(
    path: Path,
    *,
    unique_document_number: str,
    unique_amount: str,
) -> None:
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
            "TEST-DUPLICATE-001",
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
            unique_document_number,
            "0",
            unique_amount,
            "ТОВ Інший тестовий покупець",
            "UA000000000000000000000000011",
            "22222222",
            "Інша тестова оплата",
        ],
    ]

    with path.open("w", encoding="cp1251", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerows(rows)


def _write_abank_statement(path: Path) -> None:
    rows = [
        [
            "Дата операції",
            "Час операції",
            "№ платежу",
            "Тип операції",
            "Контрагент",
            "ЄДРПОУ/РНОКПП контрагента",
            "IBAN Контрагента",
            "Призначення платежу",
            "Сума, грн",
            "Залишок після операції в валюті рахунку",
        ],
        [
            "01.06.2026",
            "12:00:00",
            "TEST-ABANK-001",
            "Вхідна",
            "ТОВ Тестовий покупець",
            "11111111",
            "UA000000000000000000000000010",
            "Оплата за тестові послуги",
            "20,00",
            "20,00",
        ],
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        file.write(
            "Виписка за рахунком ФОП ТЕСТОВИЙ ТАРАС ІВАНОВИЧ "
            "UA000000000000000000000000001 UAH "
            "за період з 01.06.2026-30.06.2026\n"
        )
        writer = csv.writer(file, delimiter=",")
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
        match="requires an account number",
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


def test_run_income_book_pipeline_supports_abank(tmp_path: Path) -> None:
    statement_path = tmp_path / "statement.csv"
    checkbox_path = tmp_path / "checkbox.xlsx"
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"

    _write_abank_statement(statement_path)
    _write_checkbox_report(checkbox_path)
    _write_income_book_template(template_path)

    result = run_income_book_pipeline(
        client=_client_profile(),
        bank=BankName.ABANK,
        bank_statement_path=statement_path,
        checkbox_path=checkbox_path,
        template_path=template_path,
        output_path=output_path,
        sheet_name="2026",
    )

    assert len(result.classified_transactions) == 1
    assert result.classified_transactions[0].transaction.bank is BankName.ABANK
    assert result.daily_entries[0].bank_income == Decimal("20.00")


def test_run_income_book_pipeline_deduplicates_overlapping_statements(
    tmp_path: Path,
) -> None:
    first_statement_path = tmp_path / "first-statement.csv"
    second_statement_path = tmp_path / "second-statement.csv"
    checkbox_path = tmp_path / "checkbox.xlsx"
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"

    _write_overlapping_pumb_statement(
        first_statement_path,
        unique_document_number="TEST-UNIQUE-001",
        unique_amount="5.00",
    )
    _write_overlapping_pumb_statement(
        second_statement_path,
        unique_document_number="TEST-UNIQUE-002",
        unique_amount="7.00",
    )
    _write_checkbox_report(checkbox_path)
    _write_income_book_template(template_path)

    result = run_income_book_pipeline(
        client=_client_profile(),
        bank_statements=[
            BankStatementSource(
                bank=BankName.PUMB,
                path=first_statement_path,
            ),
            BankStatementSource(
                bank=BankName.PUMB,
                path=second_statement_path,
            ),
        ],
        checkbox_path=checkbox_path,
        template_path=template_path,
        output_path=output_path,
        sheet_name="2026",
    )

    assert len(result.classified_transactions) == 3
    assert result.daily_entries[0].bank_income == Decimal("32.00")
    assert len(result.duplicate_transactions) == 1
    assert result.duplicate_transactions[0].document_number == "TEST-DUPLICATE-001"


def test_run_income_book_pipeline_rejects_duplicate_statement_files(
    tmp_path: Path,
) -> None:
    first_statement_path = tmp_path / "first-statement.csv"
    renamed_copy_path = tmp_path / "renamed-copy.csv"

    _write_pumb_statement(first_statement_path)
    renamed_copy_path.write_bytes(first_statement_path.read_bytes())

    with pytest.raises(IncomeBookPipelineError, match="duplicates"):
        run_income_book_pipeline(
            client=_client_profile(),
            bank_statements=[
                BankStatementSource(
                    bank=BankName.PUMB,
                    path=first_statement_path,
                ),
                BankStatementSource(
                    bank=BankName.PUMB,
                    path=renamed_copy_path,
                ),
            ],
            checkbox_path=tmp_path / "checkbox.xlsx",
            template_path=tmp_path / "template.xlsx",
            output_path=tmp_path / "output.xlsx",
            sheet_name="2026",
        )


def test_run_income_book_pipeline_uses_each_mono_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_statement_path = tmp_path / "first-mono.csv"
    second_statement_path = tmp_path / "second-mono.csv"
    checkbox_path = tmp_path / "checkbox.xlsx"
    template_path = tmp_path / "template.xlsx"
    output_path = tmp_path / "output.xlsx"

    first_statement_path.write_text("first", encoding="utf-8")
    second_statement_path.write_text("second", encoding="utf-8")
    _write_checkbox_report(checkbox_path)
    _write_income_book_template(template_path)

    parsed_sources: list[tuple[Path, BankName, str | None]] = []

    def fake_parse_bank_statement(
        path: Path,
        bank: BankName,
        *,
        account_number: str | None,
    ) -> list[BankTransaction]:
        parsed_sources.append((path, bank, account_number))
        return []

    monkeypatch.setattr(
        "income_book_automation.pipeline._parse_bank_statement",
        fake_parse_bank_statement,
    )

    run_income_book_pipeline(
        client=_client_profile(),
        bank_statements=[
            BankStatementSource(
                bank=BankName.MONO,
                path=first_statement_path,
                account_number="UA000000000000000000000000101",
            ),
            BankStatementSource(
                bank=BankName.MONO,
                path=second_statement_path,
                account_number="UA000000000000000000000000102",
            ),
        ],
        checkbox_path=checkbox_path,
        template_path=template_path,
        output_path=output_path,
        sheet_name="2026",
    )

    assert parsed_sources == [
        (
            first_statement_path,
            BankName.MONO,
            "UA000000000000000000000000101",
        ),
        (
            second_statement_path,
            BankName.MONO,
            "UA000000000000000000000000102",
        ),
    ]
