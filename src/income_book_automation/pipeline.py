"""Orchestrate income-book processing from source files."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from income_book_automation.exporters.income_book import export_income_book
from income_book_automation.models import (
    BankName,
    BankTransaction,
    ClassifiedTransaction,
    ClientProfile,
    DailyIncomeBookEntry,
    TransactionCategory,
)
from income_book_automation.parsers.abank import parse_abank_file
from income_book_automation.parsers.checkbox import parse_checkbox_file
from income_book_automation.parsers.mono import parse_mono_file
from income_book_automation.parsers.privat import parse_privat_file
from income_book_automation.parsers.pumb import parse_pumb_file
from income_book_automation.rules.bank_rules import classify_bank_transaction
from income_book_automation.rules.deduplication import deduplicate_bank_transaction
from income_book_automation.rules.income_rules import (
    aggregate_bank_income_by_date,
    aggregate_checkbox_by_date,
    merge_daily_income,
)


class IncomeBookPipelineError(Exception):
    """Base error raised while running the processing pipeline."""


class MissingStatementAccountError(IncomeBookPipelineError):
    """Raised when a Mono statement account was not provided."""


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
            f"Can't read bank statement file '{path.name}'"
        ) from error

    return sha256(content).hexdigest()


def _validate_statement_accounts(
    bank_statements: list[BankStatementSource],
) -> None:
    for statement in bank_statements:
        if statement.bank is BankName.MONO and not statement.account_number:
            raise MissingStatementAccountError(
                f"Mono statement '{statement.path.name}' requires an account number"
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
                f"Bank statement '{statement.path.name}' duplicates "
                f"'{original_path.name}'"
            )

        paths_by_hash[file_hash] = statement.path


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
        bank_transactions.extend(
            _parse_bank_statement(
                statement.path,
                statement.bank,
                account_number=statement.account_number,
            )
        )
    deduplication_result = deduplicate_bank_transaction(bank_transactions)
    classified_transactions = [
        classify_bank_transaction(transaction, client)
        for transaction in deduplication_result.unique
    ]

    bank_income = aggregate_bank_income_by_date(classified_transactions)

    checkbox_records = parse_checkbox_file(checkbox_path)
    checkbox_income = aggregate_checkbox_by_date(checkbox_records)

    daily_entries = merge_daily_income(checkbox_income, bank_income)

    result_path = export_income_book(
        template_path,
        output_path,
        daily_entries,
        sheet_name=sheet_name,
    )

    return PipelineResult(
        output_path=result_path,
        daily_entries=tuple(daily_entries),
        classified_transactions=tuple(classified_transactions),
        duplicate_transactions=deduplication_result.duplicates,
    )
