from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from pytest import MonkeyPatch

from income_book_automation.config import ClientConfigValidationError
from income_book_automation.exporters.income_book import HelperColumnMapping
from income_book_automation.models import (
    BankName,
    BankTransaction,
    CheckboxPaymentMethod,
    CheckboxRefundWarning,
    ClassifiedTransaction,
    ReviewField,
    TransactionCategory,
    TransactionSource,
)
from income_book_automation.web import processing


def _upload(
    filename: str,
    content: bytes = b"synthetic-content",
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
    )


def _review_transaction() -> ClassifiedTransaction:
    transaction = BankTransaction(
        source=TransactionSource(
            original_filename="june-pumb.csv",
            row_number=17,
        ),
        date=date(2026, 6, 15),
        bank=BankName.PUMB,
        account_number="UA273000010000000000000000001",
        currency="UAH",
        document_number="TEST-REVIEW-001",
        debit=Decimal("0.00"),
        credit=Decimal("125.50"),
        counterparty="",
        counterparty_account="",
        counterparty_tax_id=None,
        payment_purpose="Оплата за послуги",
    )

    return ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.NEEDS_REVIEW,
        reason="required review fields are missing",
        missing_fields={
            ReviewField.COUNTERPARTY,
            ReviewField.COUNTERPARTY_ACCOUNT,
            ReviewField.COUNTERPARTY_TAX_ID,
        },
    )


def test_build_review_transaction_rows_maps_domain_data_for_ui() -> None:
    result = processing.build_review_transaction_rows((_review_transaction(),))

    assert result == (
        processing.ReviewTransactionRow(
            filename="june-pumb.csv",
            bank="ПУМБ",
            row_number=17,
            transaction_date="15.06.2026",
            amount="125.50 UAH",
            document_number="TEST-REVIEW-001",
            counterparty="—",
            counterparty_account="—",
            counterparty_tax_id="—",
            payment_purpose="Оплата за послуги",
            reason="Відсутні обов’язкові реквізити",
            missing_fields=(
                "Контрагент",
                "IBAN контрагента",
                "РНОКПП/ЄДРПОУ контрагента",
            ),
        ),
    )


def test_build_review_transaction_rows_explains_identity_conflict() -> None:
    transaction = _review_transaction().transaction.model_copy(
        update={
            "counterparty": "Тестовий Тарас Іванович",
            "counterparty_account": "UA273000010000000000000000001",
            "counterparty_tax_id": "2222222222",
        }
    )
    record = ClassifiedTransaction(
        transaction=transaction,
        category=TransactionCategory.NEEDS_REVIEW,
        reason="counterparty identity conflicts with client profile",
    )

    result = processing.build_review_transaction_rows((record,))

    assert result[0].reason == ("Реквізити контрагента суперечать профілю клієнта")
    assert result[0].missing_fields == ()


def _validate_request(
    *,
    client_id: str = "client-test-001",
    banks: list[BankName] | None = None,
    bank_statements: list[UploadFile] | None = None,
    account_numbers: list[str] | None = None,
    sheet_name: str = "2026",
) -> list[str | None]:
    selected_banks = [BankName.PUMB] if banks is None else banks
    selected_statements = (
        [_upload("statement.csv")] if bank_statements is None else bank_statements
    )
    selected_accounts = [""] if account_numbers is None else account_numbers

    return processing._validate_request(
        client_id=client_id,
        banks=selected_banks,
        bank_statements=selected_statements,
        account_numbers=selected_accounts,
        checkbox_report=_upload("checkbox.xlsx"),
        template_file=_upload("template.xlsx"),
        sheet_name=sheet_name,
    )


def test_validate_upload_rejects_wrong_extension() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match=(
            "Файл у полі «Банківська виписка»: «statement.pdf» "
            "має непідтримуваний формат"
        ),
    ):
        processing._validate_upload(
            _upload("statement.pdf"),
            label="Банківська виписка",
            allowed_extensions=processing.CSV_EXTENSIONS,
        )


def test_validate_upload_rejects_empty_file() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Файл у полі «Банківська виписка»: «statement.csv» порожній",
    ):
        processing._validate_upload(
            _upload("statement.csv", b""),
            label="Банківська виписка",
            allowed_extensions=processing.CSV_EXTENSIONS,
        )


def test_validate_upload_rejects_oversized_file(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(processing, "MAX_UPLOAD_SIZE_BYTES", 4)

    with pytest.raises(
        processing.UploadInputError,
        match="Файл у полі «Банківська виписка»: «statement.csv» перевищує",
    ):
        processing._validate_upload(
            _upload("statement.csv", b"12345"),
            label="Банківська виписка",
            allowed_extensions=processing.CSV_EXTENSIONS,
        )


def test_validate_request_rejects_too_many_bank_statements() -> None:
    statement_count = processing.MAX_BANK_STATEMENTS + 1

    with pytest.raises(
        processing.UploadInputError,
        match="не більше",
    ):
        _validate_request(
            banks=[BankName.PUMB] * statement_count,
            bank_statements=[
                _upload(f"statement-{index}.csv") for index in range(statement_count)
            ],
            account_numbers=[""] * statement_count,
        )


def test_validate_request_requires_selected_client() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Оберіть ФОПа зі списку",
    ):
        _validate_request(client_id="   ")


def test_validate_request_rejects_mismatched_statement_fields() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Для кожної банківської виписки",
    ):
        _validate_request(
            banks=[BankName.PUMB, BankName.ABANK],
            bank_statements=[_upload("statement.csv")],
            account_numbers=["", ""],
        )


def test_validate_request_rejects_blank_sheet_name() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Вкажіть назву листа",
    ):
        _validate_request(sheet_name="   ")


def test_validate_request_requires_mono_iban() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Mono «statement.csv» потрібно вказати IBAN",
    ):
        _validate_request(
            banks=[BankName.MONO],
            account_numbers=["   "],
        )


def test_validate_request_normalizes_mono_iban() -> None:
    result = _validate_request(
        banks=[BankName.MONO],
        account_numbers=[" ua27 300001 0000000000000000001 "],
    )

    assert result == ["UA273000010000000000000000001"]


def test_validate_request_rejects_invalid_mono_iban() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Mono «statement.csv».*некоректний український IBAN",
    ):
        _validate_request(
            banks=[BankName.MONO],
            account_numbers=["UA003000010000000000000000001"],
        )


def test_validate_request_ignores_account_for_other_banks() -> None:
    result = _validate_request(
        banks=[BankName.PUMB],
        account_numbers=["UA1234567890"],
    )

    assert result == [None]


def test_generate_from_uploads_forwards_helper_columns(
    monkeypatch: MonkeyPatch,
) -> None:
    helper_columns = HelperColumnMapping(
        total=10,
        checkbox_card=12,
        checkbox_cash=13,
        bank_income=14,
    )
    forwarded_helper_columns: list[HelperColumnMapping | None] = []
    forwarded_filenames: list[tuple[str, str, str]] = []
    forwarded_client_ids: list[tuple[processing.Path, str]] = []

    def fake_load_client_profile_by_id(
        directory: processing.Path,
        client_id: str,
    ) -> object:
        forwarded_client_ids.append((directory, client_id))
        return object()

    monkeypatch.setattr(
        processing,
        "load_client_profile_by_id",
        fake_load_client_profile_by_id,
    )

    def fake_run_income_book_pipeline(**kwargs: object) -> SimpleNamespace:
        forwarded_helper_columns.append(kwargs["helper_columns"])
        output_path = kwargs["output_path"]
        bank_statements = kwargs["bank_statements"]
        checkbox_path = kwargs["checkbox_path"]
        template_path = kwargs["template_path"]
        assert isinstance(output_path, processing.Path)
        assert isinstance(bank_statements, list)
        assert isinstance(checkbox_path, processing.Path)
        assert isinstance(template_path, processing.Path)

        forwarded_filenames.append(
            (
                bank_statements[0].path.name,
                checkbox_path.name,
                template_path.name,
            )
        )
        output_path.write_bytes(b"generated-workbook")

        return SimpleNamespace(
            daily_entries=(),
            classified_transactions=(),
            needs_review=(),
            duplicate_transactions=(),
            checkbox_warnings=(
                CheckboxRefundWarning(
                    date=date(2026, 6, 15),
                    payment_method=CheckboxPaymentMethod.CARD,
                    revenue=Decimal("5000.00"),
                    refund=Decimal("8000.00"),
                ),
            ),
            no_income=True,
        )

    monkeypatch.setattr(
        processing,
        "run_income_book_pipeline",
        fake_run_income_book_pipeline,
    )

    result = processing.generate_income_book_from_uploads(
        client_id="client-test-001",
        client_config_directory=processing.Path("/private/client-configs"),
        banks=[BankName.PUMB],
        bank_statements=[_upload("bank-original.csv")],
        account_numbers=[""],
        checkbox_report=_upload("ZReport-original.xlsx"),
        template_file=_upload("income-book-original.xlsx"),
        sheet_name="2026",
        helper_columns=helper_columns,
    )

    assert result.content == b"generated-workbook"
    assert len(result.checkbox_warnings) == 1
    assert result.checkbox_warnings[0].result == Decimal("-3000.00")
    assert result.no_income is True
    assert forwarded_helper_columns == [helper_columns]
    assert forwarded_client_ids == [
        (processing.Path("/private/client-configs"), "client-test-001")
    ]
    assert forwarded_filenames == [
        (
            "bank-original.csv",
            "ZReport-original.xlsx",
            "income-book-original.xlsx",
        )
    ]


def test_upload_filename_removes_windows_directories() -> None:
    upload = _upload(r"C:\Users\Worker\Downloads\statement-original.csv")

    assert (
        processing._upload_filename(
            upload,
            fallback_name="fallback.csv",
        )
        == "statement-original.csv"
    )


def test_generate_rejects_unknown_selected_client(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_load_client_profile_by_id(
        _directory: processing.Path,
        _client_id: str,
    ) -> object:
        raise ClientConfigValidationError("unknown client")

    monkeypatch.setattr(
        processing,
        "load_client_profile_by_id",
        fake_load_client_profile_by_id,
    )

    with pytest.raises(
        ClientConfigValidationError,
        match="unknown client",
    ):
        processing.generate_income_book_from_uploads(
            client_id="client-unknown",
            client_config_directory=processing.Path("/private/client-configs"),
            banks=[BankName.PUMB],
            bank_statements=[_upload("bank.csv")],
            account_numbers=[""],
            checkbox_report=_upload("ZReport.xlsx"),
            template_file=_upload("income-book.xlsx"),
            sheet_name="2026",
        )


def test_export_error_names_template_field_and_original_file(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        processing,
        "load_client_profile_by_id",
        lambda _directory, _client_id: object(),
    )

    def fake_run_income_book_pipeline(**_kwargs: object) -> None:
        raise processing.IncomeBookExportError("synthetic export error")

    monkeypatch.setattr(
        processing,
        "run_income_book_pipeline",
        fake_run_income_book_pipeline,
    )

    with pytest.raises(
        processing.IncomeBookExportError,
        match="шаблон книги доходів «wrong-income-book.xlsx»",
    ):
        processing.generate_income_book_from_uploads(
            client_id="client-test-001",
            client_config_directory=processing.Path("/private/client-configs"),
            banks=[BankName.PUMB],
            bank_statements=[_upload("bank.csv")],
            account_numbers=[""],
            checkbox_report=_upload("ZReport.xlsx"),
            template_file=_upload("wrong-income-book.xlsx"),
            sheet_name="2026",
        )
