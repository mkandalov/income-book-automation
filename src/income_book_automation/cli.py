"""Command-line interface for the income-book automation application."""

from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from income_book_automation.config import (
    ClientConfigError,
    load_client_profile,
)
from income_book_automation.exporters.income_book import (
    IncomeBookExportError,
)
from income_book_automation.models import BankName
from income_book_automation.parsers.checkbox import (
    CheckboxParseError,
    parse_checkbox_file,
)
from income_book_automation.parsers.errors import (
    BankStatementParseError,
)
from income_book_automation.pipeline import (
    IncomeBookPipelineError,
    run_income_book_pipeline,
)
from income_book_automation.rules.income_rules import aggregate_checkbox_by_date

app = typer.Typer(
    name="income-book",
    help="Automate income-book preparation from accounting source files.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """Automate income-book processing."""


@app.command()
def generate(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            help="Path to the private client YAML configuration.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    bank: Annotated[
        BankName,
        typer.Option(
            "--bank",
            help="Bank statement format.",
            case_sensitive=False,
        ),
    ],
    bank_statement_path: Annotated[
        Path,
        typer.Option(
            "--bank-statement",
            help="Path to the bank statement.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    checkbox_path: Annotated[
        Path,
        typer.Option(
            "--checkbox",
            help="Path to Checkbox XLSX report.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    template_path: Annotated[
        Path,
        typer.Option(
            "--template",
            help="Path to existing income-book template.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output_path: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path for the generated income book.",
            dir_okay=False,
        ),
    ],
    sheet_name: Annotated[
        str,
        typer.Option(
            "--sheet",
            help="Income-book worksheet name.",
        ),
    ],
    statement_account: Annotated[
        str | None,
        typer.Option(
            "--statement-account",
            help="Statement IBAN; required for Mono.",
        ),
    ] = None,
) -> None:
    """Generate an income book from bank and Checkbox source files."""
    try:
        client = load_client_profile(config_path)

        result = run_income_book_pipeline(
            client=client,
            bank=bank,
            bank_statement_path=bank_statement_path,
            checkbox_path=checkbox_path,
            template_path=template_path,
            output_path=output_path,
            sheet_name=sheet_name,
            statement_account=statement_account,
        )

    except (
        ClientConfigError,
        BankStatementParseError,
        CheckboxParseError,
        IncomeBookExportError,
        IncomeBookPipelineError,
    ) as error:
        console.print("[bold red]Processing failed[/bold red]")
        console.print(str(error))
        raise typer.Exit(code=1) from error

    console.print("[bold green]Income book created[/bold green]")
    console.print(f"Output: {result.output_path}")
    console.print(f"Processed days: {len(result.daily_entries)}")
    console.print(f"Bank transactions: {len(result.classified_transactions)}")
    console.print(f"Needs manual review: {len(result.needs_review)}")


@app.command()
def checkbox_summary(
    path: Annotated[
        Path,
        typer.Argument(
            help="Path to a Checkbox Z-report workbook.",
            exists=True,
            dir_okay=False,
            readable=True,
        ),
    ],
) -> None:
    """Parse a Checkbox workbook and print daily revenue totals."""
    try:
        records = parse_checkbox_file(path)
    except CheckboxParseError as error:
        print(f"Error: {error}")
        raise SystemExit(1) from error

    daily_records = aggregate_checkbox_by_date(records)

    card_total = sum((record.card_net for record in daily_records), Decimal(0))

    cash_total = sum((record.cash_net for record in daily_records), Decimal(0))

    total = card_total + cash_total

    console.print("[bold green]Checkbox report processed[/bold green]")
    console.print()
    console.print(f"Days: {len(daily_records)}")
    console.print(f"Card revenue: {card_total:,.2f}")
    console.print(f"Cash revenue: {cash_total:,.2f}")
    console.print(f"Total revenue: {total:,.2f}")
