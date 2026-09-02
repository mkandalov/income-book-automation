from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory

from fastapi import UploadFile

from income_book_automation.config import load_client_profile_by_id
from income_book_automation.exporters.income_book import (
    DuplicateMonthTotalRowError,
    HelperColumnMapping,
    IncomeBookExportError,
    IncomeBookTemplateReadError,
    IncomeBookTemplateWriteError,
    InvalidHelperColumnMappingError,
    MissingIncomeBookDateError,
    MissingIncomeBookSheetError,
    MissingMonthTotalRowError,
    MissingPreviousMonthTotalRowError,
    MissingYearTotalRowError,
)
from income_book_automation.iban import (
    InvalidUkrainianIbanError,
    normalize_ukrainian_iban,
)
from income_book_automation.models import (
    BankName,
    CheckboxRefundWarning,
    ClassifiedTransaction,
    ClientProfile,
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


class IncomeSourceMode(StrEnum):
    BOTH = "both"
    CHECKBOX_ONLY = "checkbox_only"
    BANK_ONLY = "bank_only"

    @property
    def uses_bank_statements(self) -> bool:
        return self in {self.BOTH, self.BANK_ONLY}

    @property
    def uses_checkbox(self) -> bool:
        return self in {self.BOTH, self.CHECKBOX_ONLY}


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


def _format_export_error_for_user(
    error: IncomeBookExportError,
    *,
    template_name: str,
    sheet_name: str,
) -> str:
    template_description = f"Файл у полі «Шаблон книги доходів» — «{template_name}»"
    sheet_description = f"лист «{sheet_name}»"

    if isinstance(error, IncomeBookTemplateReadError):
        return (
            f"{template_description} не вдалося відкрити як книгу XLSX. "
            "Переконайтеся, що файл не пошкоджений і має формат .xlsx."
        )

    if isinstance(error, MissingIncomeBookSheetError):
        available_sheets = ", ".join(
            f"«{available_sheet}»" for available_sheet in error.available_sheets
        )
        available_description = (
            f" Доступні листи: {available_sheets}."
            if available_sheets
            else " У книзі немає доступних листів."
        )
        return (
            f"{template_description}: не знайдено лист «{error.sheet_name}»."
            f"{available_description} Перевірте поле «Назва листа»."
        )

    if isinstance(error, MissingYearTotalRowError):
        return (
            f"{template_description}, {sheet_description}: не знайдено рядок "
            f"річного підсумку «{error.label}». Двокрапка наприкінці "
            "необов’язкова; перевірте сам текст підпису."
        )

    if isinstance(error, DuplicateMonthTotalRowError):
        expected_label = f"Всього {error.month_name}:"
        return (
            f"{template_description}, {sheet_description}: знайдено кілька "
            f"рядків підсумку за місяць «{error.month_name}». Залиште один "
            f"рядок з підписом «{expected_label}»."
        )

    if isinstance(error, MissingMonthTotalRowError):
        expected_labels = ", ".join(
            f"«Всього {month_name}:»" for month_name in error.month_names
        )
        return (
            f"{template_description}, {sheet_description}: для вже заповнених "
            "місяців не знайдено рядки підсумків. Очікувані підписи: "
            f"{expected_labels}."
        )

    if isinstance(error, MissingPreviousMonthTotalRowError):
        return (
            f"{template_description}, {sheet_description}: не знайдено жодного "
            "рядка місячного підсумку, стиль якого можна використати для нового "
            "місяця. Перевірте рядки з підписами на зразок «Всього травень:»."
        )

    if isinstance(error, MissingIncomeBookDateError):
        missing_dates = ", ".join(
            missing_date.strftime("%d.%m.%Y") for missing_date in error.missing_dates
        )
        return (
            f"{template_description}, {sheet_description}: не знайдено рядки "
            f"для дат {missing_dates}. Перевірте, чи шаблон містить потрібні "
            "дати та чи вони записані як дати Excel."
        )

    if isinstance(error, InvalidHelperColumnMappingError):
        return f"Помилка у блоці «Допоміжні колонки»: {error}"

    if isinstance(error, IncomeBookTemplateWriteError):
        return (
            "Не вдалося зберегти готову книгу доходів. Повторіть спробу. "
            "Якщо помилка повториться, зверніться до адміністратора."
        )

    return (
        f"Не вдалося заповнити шаблон книги доходів «{template_name}». "
        "Перевірте структуру шаблону та повторіть спробу."
    )


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
    client_id: str,
    source_mode: IncomeSourceMode,
    banks: list[BankName],
    bank_statements: list[UploadFile],
    account_numbers: list[str],
    checkbox_report: UploadFile | None,
    template_file: UploadFile,
    sheet_name: str,
) -> list[str | None]:
    if not client_id.strip():
        raise UploadInputError("Оберіть ФОПа зі списку.")

    if source_mode.uses_bank_statements and not banks:
        raise UploadInputError("Додайте щонайменше одну банківську виписку.")

    if len(banks) > MAX_BANK_STATEMENTS:
        raise UploadInputError(
            f"Можна додати не більше {MAX_BANK_STATEMENTS} банківських виписок."
        )

    if source_mode.uses_bank_statements and not (
        len(banks) == len(bank_statements) == len(account_numbers)
    ):
        raise UploadInputError(
            "Для кожної банківської виписки виберіть банк і заповніть "
            "пов'язане поле рахунку."
        )

    if not sheet_name.strip():
        raise UploadInputError("Вкажіть назву листа у шаблоні книги доходів.")

    if source_mode.uses_checkbox:
        if checkbox_report is None or not checkbox_report.filename:
            raise UploadInputError("Додайте Звіт по Z-звітам Checkbox.")

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
    client_id: str,
    client_config_directory: Path,
    source_mode: IncomeSourceMode,
    banks: list[BankName] | None,
    bank_statements: list[UploadFile] | None,
    account_numbers: list[str] | None,
    checkbox_report: UploadFile | None,
    template_file: UploadFile,
    sheet_name: str,
    helper_columns: HelperColumnMapping | None = None,
) -> WebGenerationResult:
    banks = banks or []
    bank_statements = bank_statements or []
    account_numbers = account_numbers or []

    if not source_mode.uses_bank_statements:
        banks = []
        bank_statements = []
        account_numbers = []

    if not source_mode.uses_checkbox:
        checkbox_report = None

    normalized_accounts = _validate_request(
        client_id=client_id,
        source_mode=source_mode,
        banks=banks,
        bank_statements=bank_statements,
        account_numbers=account_numbers,
        checkbox_report=checkbox_report,
        template_file=template_file,
        sheet_name=sheet_name,
    )
    client: ClientProfile = load_client_profile_by_id(
        client_config_directory,
        client_id,
    )

    with TemporaryDirectory(prefix="income-book-") as temporary_directory:
        workspace = Path(temporary_directory)

        checkbox_path: Path | None = None
        if checkbox_report is not None:
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

        if checkbox_report is not None and checkbox_path is not None:
            _save_upload(
                checkbox_report,
                checkbox_path,
                label="Z-звіт Checkbox",
            )
        _save_upload(
            template_file,
            template_path,
            label="шаблон книги доходів",
        )

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
                _format_export_error_for_user(
                    error,
                    template_name=template_path.name,
                    sheet_name=sheet_name,
                )
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
