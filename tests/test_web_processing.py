from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from pytest import MonkeyPatch

from income_book_automation.exporters.income_book import HelperColumnMapping
from income_book_automation.models import BankName
from income_book_automation.web import processing


def _upload(
    filename: str,
    content: bytes = b"synthetic-content",
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
    )


def _validate_request(
    *,
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
        config_file=_upload("client.yaml"),
        banks=selected_banks,
        bank_statements=selected_statements,
        account_numbers=selected_accounts,
        checkbox_report=_upload("checkbox.xlsx"),
        template_file=_upload("template.xlsx"),
        sheet_name=sheet_name,
    )


@pytest.mark.parametrize(
    "filename",
    ["client.yaml", "client.yml", "CLIENT.YML"],
)
def test_validate_upload_accepts_yaml_extensions(filename: str) -> None:
    upload = _upload(filename)

    processing._validate_upload(
        upload,
        label="Профіль клієнта",
        allowed_extensions=processing.YAML_EXTENSIONS,
    )

    assert upload.file.tell() == 0


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
        account_numbers=[" ua12 3456 7890 "],
    )

    assert result == ["UA1234567890"]


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
    forwarded_filenames: list[tuple[str, str, str, str]] = []

    def fake_load_client_profile(path: processing.Path) -> object:
        forwarded_filenames.append((path.name, "", "", ""))
        return object()

    monkeypatch.setattr(processing, "load_client_profile", fake_load_client_profile)

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

        forwarded_filenames[0] = (
            forwarded_filenames[0][0],
            bank_statements[0].path.name,
            checkbox_path.name,
            template_path.name,
        )
        output_path.write_bytes(b"generated-workbook")

        return SimpleNamespace(
            daily_entries=(),
            classified_transactions=(),
            needs_review=(),
            duplicate_transactions=(),
        )

    monkeypatch.setattr(
        processing,
        "run_income_book_pipeline",
        fake_run_income_book_pipeline,
    )

    result = processing.generate_income_book_from_uploads(
        config_file=_upload("client-original.yaml"),
        banks=[BankName.PUMB],
        bank_statements=[_upload("bank-original.csv")],
        account_numbers=[""],
        checkbox_report=_upload("ZReport-original.xlsx"),
        template_file=_upload("income-book-original.xlsx"),
        sheet_name="2026",
        helper_columns=helper_columns,
    )

    assert result.content == b"generated-workbook"
    assert forwarded_helper_columns == [helper_columns]
    assert forwarded_filenames == [
        (
            "client-original.yaml",
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


def test_config_error_names_profile_field_and_original_file(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_load_client_profile(_path: processing.Path) -> object:
        raise processing.ClientConfigError("synthetic config error")

    monkeypatch.setattr(
        processing,
        "load_client_profile",
        fake_load_client_profile,
    )

    with pytest.raises(
        processing.ClientConfigError,
        match="Профіль клієнта «wrong-client.yaml»",
    ):
        processing.generate_income_book_from_uploads(
            config_file=_upload("wrong-client.yaml"),
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
        "load_client_profile",
        lambda _path: object(),
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
            config_file=_upload("client.yaml"),
            banks=[BankName.PUMB],
            bank_statements=[_upload("bank.csv")],
            account_numbers=[""],
            checkbox_report=_upload("ZReport.xlsx"),
            template_file=_upload("wrong-income-book.xlsx"),
            sheet_name="2026",
        )
