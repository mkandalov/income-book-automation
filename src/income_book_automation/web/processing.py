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


class UploadInputError(Exception):
    """Raised when uploaded files cannot be prepared for processing."""


@dataclass(frozen=True, slots=True)
class WebGenerationResult:
    content: bytes
    processed_days: int
    bank_transactions: int
    needs_review: int
    duplicate_transactions: int


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
    if not len(banks) == len(bank_statements) == len(account_numbers):
        raise UploadInputError("Each bank statement must have a bank and account field")

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

        for index, (bank, statement, account_number) in enumerate(
            zip(banks, bank_statements, account_numbers, strict=True)
        ):
            statement_path = workspace / f"statement-{index}.csv"
            _save_upload(statement, statement_path)

            normalized_account = (
                account_number.strip().upper() if bank is BankName.MONO else None
            )

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
