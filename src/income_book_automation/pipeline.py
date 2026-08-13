"""Orchestrate income-book processing from source files."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from income_book_automation.exporters.income_book import (
    HelperColumnMapping,
    export_income_book,
)
from income_book_automation.models import (
    BankName,
    BankTransaction,
    CheckboxRefundWarning,
    ClassifiedTransaction,
    ClientProfile,
    DailyCheckboxRevenue,
    DailyIncomeBookEntry,
    TransactionCategory,
)
from income_book_automation.parsers.abank import parse_abank_file
from income_book_automation.parsers.checkbox import (
    CheckboxFormatError,
    CheckboxParseError,
    InvalidCheckboxRowError,
    MissingCheckboxColumnError,
    parse_checkbox_file,
)
from income_book_automation.parsers.errors import (
    BankStatementFormatError,
    BankStatementReadError,
    InvalidBankRowError,
)
from income_book_automation.parsers.mono import parse_mono_file
from income_book_automation.parsers.privat import parse_privat_file
from income_book_automation.parsers.pumb import parse_pumb_file
from income_book_automation.rules.bank_rules import classify_bank_transaction
from income_book_automation.rules.deduplication import deduplicate_bank_transaction
from income_book_automation.rules.income_rules import (
    aggregate_bank_income_by_date,
    aggregate_checkbox_by_date,
    find_checkbox_refund_warnings,
    merge_daily_income,
)


class IncomeBookPipelineError(Exception):
    """Base error raised while running the processing pipeline."""


class MissingStatementAccountError(IncomeBookPipelineError):
    """Raised when a Mono statement account was not provided."""


class UnsupportedCurrencyError(IncomeBookPipelineError):
    """Raised when a statement contains a non-UAH transaction."""


class MixedPeriodError(IncomeBookPipelineError):
    """Raised when uploaded sources contain different calendar months."""


class UnresolvedTransactionsError(IncomeBookPipelineError):
    """Raised when transactions require manual review before export."""

    def __init__(self, records: tuple[ClassifiedTransaction, ...]) -> None:
        self.records = records

        super().__init__(f"{len(records)} bank transaction(s) require manual review")


BANK_DISPLAY_NAMES = {
    BankName.PUMB: "ПУМБ",
    BankName.PRIVAT: "ПриватБанк",
    BankName.MONO: "Mono",
    BankName.ABANK: "А-Банк",
}


@dataclass(frozen=True, slots=True)
class BankStatementSource:
    bank: BankName
    path: Path
    account_number: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    output_path: Path
    daily_entries: tuple[DailyIncomeBookEntry, ...]
    classified_transactions: tuple[ClassifiedTransaction, ...]
    duplicate_transactions: tuple[BankTransaction, ...]
    checkbox_warnings: tuple[CheckboxRefundWarning, ...]

    @property
    def no_income(self) -> bool:
        return not self.daily_entries

    @property
    def needs_review(self) -> tuple[ClassifiedTransaction, ...]:
        return tuple(
            record
            for record in self.classified_transactions
            if record.category is TransactionCategory.NEEDS_REVIEW
        )


def _calculate_file_hash(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise IncomeBookPipelineError(
            f"Не вдалося прочитати банківську виписку «{path.name}» "
            "під час перевірки файлу. Виберіть її ще раз."
        ) from error

    return sha256(content).hexdigest()


def _validate_statement_accounts(
    bank_statements: list[BankStatementSource],
) -> None:
    for statement in bank_statements:
        if statement.bank is BankName.MONO and not statement.account_number:
            raise MissingStatementAccountError(
                f"Для банківської виписки Mono «{statement.path.name}» "
                "потрібно вказати IBAN рахунку."
            )


def _validate_unique_statement_files(
    bank_statements: list[BankStatementSource],
) -> None:
    paths_by_hash: dict[str, Path] = {}

    for statement in bank_statements:
        file_hash = _calculate_file_hash(statement.path)
        original_path = paths_by_hash.get(file_hash)

        if original_path is not None:
            raise IncomeBookPipelineError(
                f"Банківська виписка «{statement.path.name}» повторює "
                f"вже доданий файл «{original_path.name}». Видаліть один "
                "із цих файлів."
            )

        paths_by_hash[file_hash] = statement.path


def _validate_transaction_currencies(
    transactions: list[BankTransaction],
) -> None:
    for transaction in transactions:
        currency = transaction.currency.strip().upper()

        if currency != "UAH":
            raise UnsupportedCurrencyError(
                f"Банківська виписка "
                f"«{transaction.source.original_filename}», "
                f"рядок {transaction.source.row_number}: "
                f"валюта {currency} не підтримується. "
                "Книга доходів формується лише у валюті UAH."
            )


def _validate_single_processing_period(
    bank_transactions: list[BankTransaction],
    checkbox_records: list[DailyCheckboxRevenue],
    *,
    checkbox_filename: str,
) -> None:
    periods_by_file: dict[str, set[str]] = {}

    for transaction in bank_transactions:
        filename = transaction.source.original_filename
        period = f"{transaction.date.year}-{transaction.date.month:02d}"

        periods_by_file.setdefault(filename, set()).add(period)

    checkbox_periods = {
        f"{record.date.year}-{record.date.month:02d}" for record in checkbox_records
    }

    periods_by_file[checkbox_filename] = checkbox_periods

    all_periods = {period for periods in periods_by_file.values() for period in periods}

    if len(all_periods) <= 1:
        return

    details = "; ".join(
        f"«{filename}»: {', '.join(sorted(periods))}"
        for filename, periods in periods_by_file.items()
    )

    raise MixedPeriodError(
        f"Завантажені файли містять дані за різні місяці: {details}. "
        "Можна обробити лише один календарний місяць за один запуск."
    )


def _parse_bank_statement(
    path: Path,
    bank: BankName,
    *,
    account_number: str | None,
) -> list[BankTransaction]:
    match bank:
        case BankName.ABANK:
            return parse_abank_file(path)
        case BankName.PUMB:
            return parse_pumb_file(path)
        case BankName.PRIVAT:
            return parse_privat_file(path)
        case BankName.MONO:
            if not account_number:
                raise MissingStatementAccountError("Mono statement account is required")
            return parse_mono_file(
                path,
                account_number=account_number,
            )
    raise IncomeBookPipelineError(f"unsupported bank: {bank}")


def run_income_book_pipeline(
    *,
    client: ClientProfile,
    bank: BankName | None = None,
    bank_statement_path: Path | None = None,
    bank_statements: list[BankStatementSource] | None = None,
    checkbox_path: Path,
    template_path: Path,
    output_path: Path,
    sheet_name: str,
    statement_account: str | None = None,
    helper_columns: HelperColumnMapping | None = None,
) -> PipelineResult:
    if bank_statements is None:
        if bank is None or bank_statement_path is None:
            raise IncomeBookPipelineError("at least one bank statement is required")
        bank_statements = [
            BankStatementSource(
                bank=bank,
                path=bank_statement_path,
                account_number=statement_account,
            )
        ]

    _validate_statement_accounts(bank_statements)
    _validate_unique_statement_files(bank_statements)

    bank_transactions: list[BankTransaction] = []
    for statement in bank_statements:
        try:
            transactions = _parse_bank_statement(
                statement.path,
                statement.bank,
                account_number=statement.account_number,
            )

        except InvalidBankRowError as error:
            bank_name = BANK_DISPLAY_NAMES[statement.bank]

            raise InvalidBankRowError(
                f"У банківській виписці «{statement.path.name}», вибраній "
                f"для банку {bank_name}, знайдено некоректні дані. "
                f"Деталі: {error}"
            ) from error
        except (BankStatementReadError, BankStatementFormatError) as error:
            bank_name = BANK_DISPLAY_NAMES[statement.bank]

            raise BankStatementFormatError(
                f"Файл «{statement.path.name}» не вдалося прочитати як "
                f"виписку банку {bank_name}. Перевірте, чи для цього файлу "
                "правильно вибрано банк і чи виписку експортовано у форматі CSV."
            ) from error
        _validate_transaction_currencies(transactions)
        bank_transactions.extend(transactions)
    deduplication_result = deduplicate_bank_transaction(bank_transactions)
    classified_transactions = [
        classify_bank_transaction(transaction, client)
        for transaction in deduplication_result.unique
    ]

    needs_review = tuple(
        record
        for record in classified_transactions
        if record.category is TransactionCategory.NEEDS_REVIEW
    )

    if needs_review:
        raise UnresolvedTransactionsError(needs_review)

    bank_income = aggregate_bank_income_by_date(classified_transactions)

    try:
        checkbox_records = parse_checkbox_file(checkbox_path)
    except MissingCheckboxColumnError:
        raise
    except CheckboxFormatError as error:
        raise CheckboxFormatError(
            f"Файл «{checkbox_path.name}» не розпізнано як Z-звіт Checkbox. "
            "Завантажте саме Z-звіт Checkbox у форматі XLSX."
        ) from error
    except InvalidCheckboxRowError as error:
        raise InvalidCheckboxRowError(
            f"У Z-звіті Checkbox «{checkbox_path.name}» знайдено "
            f"некоректні дані. Деталі: {error}"
        ) from error
    except CheckboxParseError as error:
        raise CheckboxParseError(
            f"Не вдалося прочитати файл «{checkbox_path.name}» як Z-звіт "
            "Checkbox. Перевірте файл і повторіть завантаження."
        ) from error

    _validate_single_processing_period(
        bank_transactions,
        checkbox_records,
        checkbox_filename=checkbox_path.name,
    )
    checkbox_income = aggregate_checkbox_by_date(checkbox_records)
    checkbox_warnings = find_checkbox_refund_warnings(checkbox_income)

    daily_entries = merge_daily_income(checkbox_income, bank_income)

    result_path = export_income_book(
        template_path,
        output_path,
        daily_entries,
        sheet_name=sheet_name,
        helper_columns=helper_columns,
    )

    return PipelineResult(
        output_path=result_path,
        daily_entries=tuple(daily_entries),
        classified_transactions=tuple(classified_transactions),
        duplicate_transactions=deduplication_result.duplicates,
        checkbox_warnings=tuple(checkbox_warnings),
    )
