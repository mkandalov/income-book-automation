from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory

from fastapi import UploadFile

from income_book_automation.config import ClientConfigError, load_client_profile
from income_book_automation.exporters.income_book import (
    HelperColumnMapping,
    IncomeBookExportError,
)
from income_book_automation.iban import (
    InvalidUkrainianIbanError,
    normalize_ukrainian_iban,
)
from income_book_automation.models import (
    BankName,
    CheckboxRefundWarning,
    ClassifiedTransaction,
    ReviewField,
)
from income_book_automation.pipeline import (
    BANK_DISPLAY_NAMES,
    BankStatementSource,
    run_income_book_pipeline,
)

MAX_BANK_STATEMENTS = 10
MAX_UPLOAD_SIZE_MB = 20
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

YAML_EXTENSIONS = frozenset({".yaml", ".yml"})
CSV_EXTENSIONS = frozenset({".csv"})
XLSX_EXTENSIONS = frozenset({".xlsx"})

REVIEW_FIELD_LABELS = {
    ReviewField.DOCUMENT_NUMBER: "Номер документа",
    ReviewField.COUNTERPARTY: "Контрагент",
    ReviewField.COUNTERPARTY_ACCOUNT: "IBAN контрагента",
    ReviewField.COUNTERPARTY_TAX_ID: "РНОКПП/ЄДРПОУ контрагента",
    ReviewField.PAYMENT_PURPOSE: "Призначення платежу",
}

REVIEW_REASON_LABELS = {
    "required review fields are missing": "Відсутні обов’язкові реквізити",
    "counterparty identity conflicts with client profile": (
        "Реквізити контрагента суперечать профілю клієнта"
    ),
}


class UploadInputError(Exception):
    """Raised when uploaded files cannot be prepared for processing."""


@dataclass(frozen=True, slots=True)
class WebGenerationResult:
    content: bytes
    processed_days: int
    bank_transactions: int
    needs_review: int
    duplicate_transactions: int
    checkbox_warnings: tuple[CheckboxRefundWarning, ...] = ()
    no_income: bool = False


@dataclass(frozen=True, slots=True)
class ReviewTransactionRow:
    filename: str
    bank: str
    row_number: int
    transaction_date: str
    amount: str
    document_number: str
    counterparty: str
    counterparty_account: str
    counterparty_tax_id: str
    payment_purpose: str
    reason: str
    missing_fields: tuple[str, ...]


def _display_value(value: str | None) -> str:
    normalized_value = (value or "").strip()
    return normalized_value or "—"


def _validate_upload(
    upload: UploadFile,
    *,
    label: str,
    allowed_extensions: frozenset[str],
) -> None:
    if not upload.filename:
        raise UploadInputError(f"Для поля «{label}» не вказано назву файлу.")

    filename = _upload_filename(upload, fallback_name="файл без назви")
    description = f"Файл у полі «{label}»: «{filename}»"

    extension = Path(upload.filename).suffix.casefold()

    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))

        raise UploadInputError(
            f"{description} має непідтримуваний формат. "
            f"Дозволені розширення: {allowed}."
        )

    try:
        upload.file.seek(0, 2)
        file_size = upload.file.tell()
        upload.file.seek(0)
    except (OSError, ValueError) as error:
        raise UploadInputError(
            f"Не вдалося перевірити {description}. Виберіть файл ще раз."
        ) from error

    if file_size == 0:
        raise UploadInputError(f"{description} порожній. Виберіть інший файл.")

    if file_size > MAX_UPLOAD_SIZE_BYTES:
        raise UploadInputError(
            f"{description} перевищує максимальний розмір {MAX_UPLOAD_SIZE_MB} МБ."
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
        raise UploadInputError("Додайте щонайменше одну банківську виписку.")

    if len(banks) > MAX_BANK_STATEMENTS:
        raise UploadInputError(
            f"Можна додати не більше {MAX_BANK_STATEMENTS} банківських виписок."
        )

    if not len(banks) == len(bank_statements) == len(account_numbers):
        raise UploadInputError(
            "Для кожної банківської виписки виберіть банк і заповніть "
            "пов'язане поле рахунку."
        )

    if not sheet_name.strip():
        raise UploadInputError("Вкажіть назву листа у шаблоні книги доходів.")

    _validate_upload(
        config_file,
        label="Профіль клієнта",
        allowed_extensions=YAML_EXTENSIONS,
    )

    _validate_upload(
        checkbox_report,
        label="Z-звіт Checkbox",
        allowed_extensions=XLSX_EXTENSIONS,
    )

    _validate_upload(
        template_file,
        label="Шаблон книги доходів",
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
            label=f"Банківська виписка {index}",
            allowed_extensions=CSV_EXTENSIONS,
        )

        if bank is BankName.MONO:
            normalized_account = "".join(account_number.split()).upper()

            if not normalized_account:
                statement_name = _upload_filename(
                    statement,
                    fallback_name=f"виписка {index}",
                )
                raise UploadInputError(
                    f"Для банківської виписки Mono «{statement_name}» "
                    "потрібно вказати IBAN рахунку."
                )

            try:
                normalized_account = normalize_ukrainian_iban(normalized_account)
            except InvalidUkrainianIbanError as error:
                statement_name = _upload_filename(
                    statement,
                    fallback_name=f"виписка {index}",
                )
                raise UploadInputError(
                    f"Для банківської виписки Mono «{statement_name}» "
                    "вказано некоректний український IBAN."
                ) from error
            normalized_accounts.append(normalized_account)

        else:
            normalized_accounts.append(None)

    return normalized_accounts


def _save_upload(
    upload: UploadFile,
    destination: Path,
    *,
    label: str,
) -> None:
    if not upload.filename:
        raise UploadInputError(f"Для поля «{label}» не вказано назву файлу.")
    try:
        upload.file.seek(0)

        with destination.open("wb") as output_file:
            copyfileobj(upload.file, output_file)
    except OSError as error:
        filename = _upload_filename(upload, fallback_name="файл без назви")
        raise UploadInputError(
            f"Не вдалося підготувати {label} «{filename}» до обробки. "
            "Виберіть файл ще раз."
        ) from error


def _upload_filename(
    upload: UploadFile,
    *,
    fallback_name: str,
) -> str:
    raw_filename = (upload.filename or "").replace("\\", "/")
    filename = raw_filename.rsplit("/", maxsplit=1)[-1].strip()
    filename = "".join(character for character in filename if character.isprintable())

    if filename in {"", ".", ".."}:
        return fallback_name

    return filename


def _original_upload_path(
    workspace: Path,
    directory_name: str,
    upload: UploadFile,
    *,
    fallback_name: str,
) -> Path:
    filename = _upload_filename(upload, fallback_name=fallback_name)

    upload_directory = workspace / directory_name
    upload_directory.mkdir(parents=True, exist_ok=True)

    return upload_directory / filename


def build_review_transaction_rows(
    records: tuple[ClassifiedTransaction, ...],
) -> tuple[ReviewTransactionRow, ...]:
    rows: list[ReviewTransactionRow] = []

    for record in records:
        transaction = record.transaction

        missing_fields = tuple(
            REVIEW_FIELD_LABELS[field]
            for field in ReviewField
            if field in record.missing_fields
        )

        rows.append(
            ReviewTransactionRow(
                filename=transaction.source.original_filename,
                bank=BANK_DISPLAY_NAMES[transaction.bank],
                row_number=transaction.source.row_number,
                transaction_date=transaction.date.strftime("%d.%m.%Y"),
                amount=f"{transaction.credit:.2f} {transaction.currency}",
                document_number=_display_value(transaction.document_number),
                counterparty=_display_value(transaction.counterparty),
                counterparty_account=_display_value(transaction.counterparty_account),
                counterparty_tax_id=_display_value(transaction.counterparty_tax_id),
                payment_purpose=_display_value(transaction.payment_purpose),
                reason=REVIEW_REASON_LABELS.get(
                    record.reason,
                    "Операція потребує ручної перевірки",
                ),
                missing_fields=missing_fields,
            )
        )

    return tuple(rows)


def generate_income_book_from_uploads(
    *,
    config_file: UploadFile,
    banks: list[BankName],
    bank_statements: list[UploadFile],
    account_numbers: list[str],
    checkbox_report: UploadFile,
    template_file: UploadFile,
    sheet_name: str,
    helper_columns: HelperColumnMapping | None = None,
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

        config_path = _original_upload_path(
            workspace,
            "config",
            config_file,
            fallback_name="client.yaml",
        )
        checkbox_path = _original_upload_path(
            workspace,
            "checkbox",
            checkbox_report,
            fallback_name="checkbox.xlsx",
        )
        template_path = _original_upload_path(
            workspace,
            "template",
            template_file,
            fallback_name="template.xlsx",
        )
        output_path = workspace / "result.xlsx"

        _save_upload(config_file, config_path, label="профіль клієнта")
        _save_upload(checkbox_report, checkbox_path, label="Z-звіт Checkbox")
        _save_upload(
            template_file,
            template_path,
            label="шаблон книги доходів",
        )

        try:
            client = load_client_profile(config_path)
        except ClientConfigError as error:
            raise ClientConfigError(
                f"Профіль клієнта «{config_path.name}» містить помилку. "
                "Перевірте структуру та обов'язкові поля YAML-файлу."
            ) from error

        sources: list[BankStatementSource] = []

        for index, (bank, statement, normalized_account) in enumerate(
            zip(banks, bank_statements, normalized_accounts, strict=True)
        ):
            statement_path = _original_upload_path(
                workspace,
                f"statement-{index}",
                statement,
                fallback_name=f"statement-{index}.csv",
            )
            _save_upload(
                statement,
                statement_path,
                label=f"банківську виписку {index + 1}",
            )

            sources.append(
                BankStatementSource(
                    bank=bank,
                    path=statement_path,
                    account_number=normalized_account,
                )
            )
        try:
            pipeline_result = run_income_book_pipeline(
                client=client,
                bank_statements=sources,
                checkbox_path=checkbox_path,
                template_path=template_path,
                output_path=output_path,
                sheet_name=sheet_name,
                helper_columns=helper_columns,
            )
        except IncomeBookExportError as error:
            raise IncomeBookExportError(
                f"Не вдалося заповнити шаблон книги доходів "
                f"«{template_path.name}». Перевірте, чи правильно вказано "
                "назву листа та чи шаблон має потрібну структуру."
            ) from error

        try:
            result_content = output_path.read_bytes()
        except OSError as error:
            raise UploadInputError(
                "Не вдалося підготувати готову книгу доходів до завантаження."
            ) from error

        return WebGenerationResult(
            content=result_content,
            processed_days=len(pipeline_result.daily_entries),
            bank_transactions=len(pipeline_result.classified_transactions),
            needs_review=len(pipeline_result.needs_review),
            duplicate_transactions=len(pipeline_result.duplicate_transactions),
            checkbox_warnings=tuple(pipeline_result.checkbox_warnings),
            no_income=pipeline_result.no_income,
        )
