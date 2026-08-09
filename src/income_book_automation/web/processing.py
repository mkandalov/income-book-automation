from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory

from fastapi import UploadFile

from income_book_automation.config import load_client_profile
from income_book_automation.models import BankName
from income_book_automation.pipeline import (
    BankStatementSource,
    run_income_book_pipeline,
)

MAX_BANK_STATEMENTS = 10
MAX_UPLOAD_SIZE_MB = 20
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

YAML_EXTENSIONS = frozenset({".yaml", ".yml"})
CSV_EXTENSIONS = frozenset({".csv"})
XLSX_EXTENSIONS = frozenset({".xlsx"})


class UploadInputError(Exception):
    """Raised when uploaded files cannot be prepared for processing."""


@dataclass(frozen=True, slots=True)
class WebGenerationResult:
    content: bytes
    processed_days: int
    bank_transactions: int
    needs_review: int
    duplicate_transactions: int


def _validate_upload(
    upload: UploadFile,
    *,
    label: str,
    allowed_extensions: frozenset[str],
) -> None:
    if not upload.filename:
        raise UploadInputError(f"{label} has no filename")

    extension = Path(upload.filename).suffix.casefold()

    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))

        raise UploadInputError(f"{label} must use one of these extensions: {allowed}")

    try:
        upload.file.seek(0, 2)
        file_size = upload.file.tell()
        upload.file.seek(0)
    except (OSError, ValueError) as error:
        raise UploadInputError(
            f"Cannot inspect uploaded file: {upload.filename}"
        ) from error

    if file_size == 0:
        raise UploadInputError(f"{label} cannot be empty")

    if file_size > MAX_UPLOAD_SIZE_BYTES:
        raise UploadInputError(
            f"{label} exceeds the maximum size of {MAX_UPLOAD_SIZE_MB} MB"
        )


def _validate_request(
    *,
    config_file: UploadFile,
    banks: list[BankName],
    bank_statements: list[UploadFile],
    account_numbers: list[str],
    checkbox_report: UploadFile,
    template_file: UploadFile,
    sheet_name: str,
) -> list[str | None]:
    if not banks:
        raise UploadInputError("At least one bank statement is required")

    if len(banks) > MAX_BANK_STATEMENTS:
        raise UploadInputError(
            f"No more than {MAX_BANK_STATEMENTS} bank statements are allowed"
        )

    if not len(banks) == len(bank_statements) == len(account_numbers):
        raise UploadInputError("Each bank statement must have a bank and account field")

    if not sheet_name.strip():
        raise UploadInputError("Sheet name cannot be empty")

    _validate_upload(
        config_file,
        label="Client configuration",
        allowed_extensions=YAML_EXTENSIONS,
    )

    _validate_upload(
        checkbox_report,
        label="Checkbox report",
        allowed_extensions=XLSX_EXTENSIONS,
    )

    _validate_upload(
        template_file,
        label="Income-book template",
        allowed_extensions=XLSX_EXTENSIONS,
    )

    normalized_accounts: list[str | None] = []

    for index, (bank, statement, account_number) in enumerate(
        zip(
            banks,
            bank_statements,
            account_numbers,
            strict=True,
        ),
        start=1,
    ):
        _validate_upload(
            statement,
            label=f"Bank statement {index}",
            allowed_extensions=CSV_EXTENSIONS,
        )

        if bank is BankName.MONO:
            normalized_account = "".join(account_number.split()).upper()

            if not normalized_account:
                raise UploadInputError(f"Mono statement {index} requires an IBAN")
            normalized_accounts.append(normalized_account)

        else:
            normalized_accounts.append(None)

    return normalized_accounts


def _save_upload(
    upload: UploadFile,
    destination: Path,
) -> None:
    if not upload.filename:
        raise UploadInputError("Uploaded file has no name")
    try:
        upload.file.seek(0)

        with destination.open("wb") as output_file:
            copyfileobj(upload.file, output_file)
    except OSError as error:
        raise UploadInputError(
            f"Cannot save uploaded file: {upload.filename}"
        ) from error


def generate_income_book_from_uploads(
    *,
    config_file: UploadFile,
    banks: list[BankName],
    bank_statements: list[UploadFile],
    account_numbers: list[str],
    checkbox_report: UploadFile,
    template_file: UploadFile,
    sheet_name: str,
) -> WebGenerationResult:
    normalized_accounts = _validate_request(
        config_file=config_file,
        banks=banks,
        bank_statements=bank_statements,
        account_numbers=account_numbers,
        checkbox_report=checkbox_report,
        template_file=template_file,
        sheet_name=sheet_name,
    )

    with TemporaryDirectory(prefix="income-book-") as temporary_directory:
        workspace = Path(temporary_directory)

        config_path = workspace / "client.yaml"
        checkbox_path = workspace / "checkbox.xlsx"
        template_path = workspace / "template.xlsx"
        output_path = workspace / "result.xlsx"

        _save_upload(config_file, config_path)
        _save_upload(checkbox_report, checkbox_path)
        _save_upload(template_file, template_path)

        client = load_client_profile(config_path)

        sources: list[BankStatementSource] = []

        for index, (bank, statement, normalized_account) in enumerate(
            zip(banks, bank_statements, normalized_accounts, strict=True)
        ):
            statement_path = workspace / f"statement-{index}.csv"
            _save_upload(statement, statement_path)

            sources.append(
                BankStatementSource(
                    bank=bank,
                    path=statement_path,
                    account_number=normalized_account,
                )
            )
        pipeline_result = run_income_book_pipeline(
            client=client,
            bank_statements=sources,
            checkbox_path=checkbox_path,
            template_path=template_path,
            output_path=output_path,
            sheet_name=sheet_name,
        )

        try:
            result_content = output_path.read_bytes()
        except OSError as error:
            raise UploadInputError("Cannot read generated income book") from error

        return WebGenerationResult(
            content=result_content,
            processed_days=len(pipeline_result.daily_entries),
            bank_transactions=len(pipeline_result.classified_transactions),
            needs_review=len(pipeline_result.needs_review),
            duplicate_transactions=len(pipeline_result.duplicate_transactions),
        )
