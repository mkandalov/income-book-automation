"""Orchestrate income-book processing from source files."""

from dataclasses import dataclass
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
from income_book_automation.parsers.checkbox import parse_checkbox_file
from income_book_automation.parsers.mono import parse_mono_file
from income_book_automation.parsers.privat import parse_privat_file
from income_book_automation.parsers.pumb import parse_pumb_file
from income_book_automation.rules.bank_rules import classify_bank_transaction
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
class PipelineResult:
    output_path: Path
    daily_entries: tuple[DailyIncomeBookEntry, ...]
    classified_transactions: tuple[ClassifiedTransaction, ...]

    @property
    def needs_review(self) -> tuple[ClassifiedTransaction, ...]:
        return tuple(
            record
            for record in self.classified_transactions
            if record.category is TransactionCategory.NEEDS_REVIEW
        )


def _parse_bank_statement(
    path: Path,
    bank: BankName,
    *,
    statement_account: str | None,
) -> list[BankTransaction]:
    match bank:
        case BankName.PUMB:
            return parse_pumb_file(path)
        case BankName.PRIVAT:
            return parse_privat_file(path)
        case BankName.MONO:
            if not statement_account:
                raise MissingStatementAccountError("Mono statement account is required")
            return parse_mono_file(
                path,
                account_number=statement_account,
            )
    raise IncomeBookPipelineError(f"unsupported bank: {bank}")


def run_income_book_pipeline(
    *,
    client: ClientProfile,
    bank: BankName,
    bank_statement_path: Path,
    checkbox_path: Path,
    template_path: Path,
    output_path: Path,
    sheet_name: str,
    statement_account: str | None = None,
) -> PipelineResult:
    bank_transactions = _parse_bank_statement(
        bank_statement_path,
        bank,
        statement_account=statement_account,
    )

    classified_transactions = [
        classify_bank_transaction(transaction, client)
        for transaction in bank_transactions
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
    )
