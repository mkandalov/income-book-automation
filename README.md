# Income Book Automation

A production-oriented Python pipeline for automating income-book preparation
for Ukrainian accounting workflows. The current MVP parses Checkbox Z-report
workbooks, validates monetary values, aggregates multiple shifts by opening
date, and exposes the result through a command-line interface.

The project is based on a real accounting workflow, while all client files and
identifying data remain outside the repository.

## Current features

- Parse Checkbox `.xlsx` Z-report exports with `openpyxl`.
- Represent money with `Decimal` and validate records with Pydantic.
- Calculate net card and cash revenue after refunds.
- Aggregate multiple reports into one daily record.
- Print a monthly revenue summary through a Typer CLI.
- Verify parsing and business rules with pytest and Ruff.

## Data pipeline

```text
Checkbox workbook
        ↓
parse_checkbox_file()
        ↓
DailyCheckboxRevenue records
        ↓
aggregate_checkbox_by_date()
        ↓
CLI summary / future income-book exporter
```

The detailed field mapping and accounting decisions are documented in
[`docs/rules.md`](docs/rules.md).

## Installation

The project requires Python 3.12+ and uses
[`uv`](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone https://github.com/mkandalov/income-book-automation.git
cd income-book-automation
uv sync
```

## Usage

Display available commands:

```bash
uv run income-book --help
```

Parse a Checkbox report and print daily and monthly totals:

```bash
uv run income-book checkbox-summary /path/to/checkbox-report.xlsx
```

Example output with synthetic values:

```text
Checkbox report processed

Days: 2
Card revenue: 36,487.00
Cash revenue: 900.00
Total revenue: 37,387.00
```

## Development checks

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
```

## Privacy

PDF, Excel, CSV, generated output, and private-data directories are excluded
from version control. Tests build temporary workbooks from synthetic data, so
the repository contains no client transactions or personal identifiers.

## Roadmap

- Parse bank-statement PDFs and classify eligible credit transactions.
- Reconcile Checkbox and bank totals.
- Write daily values into an existing income-book template.
- Produce an audit report with warnings and reconciliation results.
- Add CI checks and package-level error handling.
