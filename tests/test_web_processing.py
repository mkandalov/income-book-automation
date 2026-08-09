from io import BytesIO

import pytest
from fastapi import UploadFile
from pytest import MonkeyPatch

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
        label="Client configuration",
        allowed_extensions=processing.YAML_EXTENSIONS,
    )

    assert upload.file.tell() == 0


def test_validate_upload_rejects_wrong_extension() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="must use one of these extensions",
    ):
        processing._validate_upload(
            _upload("statement.pdf"),
            label="Bank statement",
            allowed_extensions=processing.CSV_EXTENSIONS,
        )


def test_validate_upload_rejects_empty_file() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="cannot be empty",
    ):
        processing._validate_upload(
            _upload("statement.csv", b""),
            label="Bank statement",
            allowed_extensions=processing.CSV_EXTENSIONS,
        )


def test_validate_upload_rejects_oversized_file(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(processing, "MAX_UPLOAD_SIZE_BYTES", 4)

    with pytest.raises(
        processing.UploadInputError,
        match="exceeds the maximum size",
    ):
        processing._validate_upload(
            _upload("statement.csv", b"12345"),
            label="Bank statement",
            allowed_extensions=processing.CSV_EXTENSIONS,
        )


def test_validate_request_rejects_too_many_bank_statements() -> None:
    statement_count = processing.MAX_BANK_STATEMENTS + 1

    with pytest.raises(
        processing.UploadInputError,
        match="No more than",
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
        match="Each bank statement must have",
    ):
        _validate_request(
            banks=[BankName.PUMB, BankName.ABANK],
            bank_statements=[_upload("statement.csv")],
            account_numbers=["", ""],
        )


def test_validate_request_rejects_blank_sheet_name() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="Sheet name cannot be empty",
    ):
        _validate_request(sheet_name="   ")


def test_validate_request_requires_mono_iban() -> None:
    with pytest.raises(
        processing.UploadInputError,
        match="requires an IBAN",
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
