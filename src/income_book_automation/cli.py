"""Command-line interface for the income-book automation application."""

from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from income_book_automation.parsers.checkbox import (
    CheckboxParseError,
    parse_checkbox_file,
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
