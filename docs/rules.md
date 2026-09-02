# Business rules

This document is the deterministic rule specification implemented by Income
Book Automation. It describes how uploaded source records become daily
income-book entries and which situations stop processing or require an
accountant's attention.

The application assists an accountant; it does not replace final professional
review.

## 1. Interfaces and processing scope

The same pipeline is used by the web application and CLI.

### Web request

One web request contains:

- one client selected from the private server-side catalog;
- one source mode: both sources, only Checkbox, or only bank statements;
- when bank data is selected, between one and ten statement CSV files and one
  selected bank format for every statement;
- one statement IBAN for every selected Monobank statement;
- when Checkbox is selected, one Checkbox Z-report XLSX workbook;
- one existing income-book XLSX template;
- a target worksheet name;
- four optional helper-column assignments;
- an optional output filename.

Employees do not upload client YAML files. The browser submits an opaque client
selector ID, and the server resolves it inside the configured client directory.

### CLI request

The CLI receives a path to one private client YAML profile and one or more
bank/statement pairs. `--bank` and `--bank-statement` values must have matching
order and count. One `--mono-account` value is required for every Monobank
statement.

### Calendar scope

All incoming bank transactions and Checkbox rows in one run must belong to one
calendar month. Outgoing debits do not define the month because some bank
exports include next-day service fees after the requested period. A mismatch
between income sources is a hard error. The error identifies each original
filename and its detected month.

## 2. Client catalog and identity

Each private YAML profile contains:

| Field | Required | Purpose |
| --- | --- | --- |
| `client_id` | yes | Stable private internal identifier |
| `legal_name` | yes | Exact normalized own-name detection |
| `tax_id` | yes | Own-transfer detection by РНОКПП/ЄДРПОУ |
| `own_accounts` | no | Known Ukrainian IBANs belonging to the client |
| `name_aliases` | no | Alternative exact names found in statements |

An empty `own_accounts` list is valid. Own-transfer detection can still use tax
ID, legal name, and aliases.

Before comparison:

- IBAN whitespace is removed and letters are uppercased;
- every configured own IBAN must contain `UA` plus 27 digits and pass the ISO
  13616 checksum;
- tax IDs are reduced to digits;
- names are case-folded, hyphens become spaces, repeated whitespace is
  collapsed;
- name matching is exact after normalization, not substring or fuzzy matching.

The web selector exposes the display name and an opaque SHA-256-derived option
ID. It does not expose the private `client_id` or tax ID in the page.

The administrative profile generator reads full names and 10-digit tax IDs from
an XLSX register, validates the complete register and duplicate tax IDs, creates
common exact-name aliases, and only then writes YAML files into an empty output
directory.

## 3. Web input validation

Before the pipeline starts, the web layer enforces:

- a client must be selected;
- the selected mode must contain at least one income source;
- when bank data is selected, at least one and at most ten statements are
  accepted;
- bank, statement, and account-input lists must have equal lengths when bank
  data is selected;
- every Monobank statement requires a valid Ukrainian statement IBAN;
- bank statements must use `.csv`;
- Checkbox and income-book uploads must use `.xlsx`;
- every upload must be non-empty and at most 20 MB;
- the target worksheet name must not be blank;
- helper assignments must use four unique column numbers from 10 through 15.

Validation errors identify the form field and original filename whenever the
problem belongs to an uploaded file.

Uploads are copied into a request-specific temporary directory. Original
basenames are retained for error reporting. The temporary directory and all
copied uploads are removed when the request ends.

## 4. Checkbox parsing and calculations

Checkbox fields are resolved by normalized header text rather than hard-coded
Excel positions. Columns may therefore be reordered.

| Business value | Required header |
| --- | --- |
| Business date | `Дата відкриття` |
| Card revenue | `Виручка безготівка` |
| Card refund | `Повернення безготівка` |
| Cash revenue | `Виручка готівка` |
| Cash refund | `Повернення готівка` |

The business date is the date component of `Дата відкриття`. A fully blank row
is skipped. A partially populated row with no opening date is a hard error.

For each parsed row:

```text
card_net = card_revenue - card_refund
cash_net = cash_revenue - cash_refund
checkbox_total = card_net + cash_net
```

Monetary policy:

- explicit numeric zero is valid;
- an empty required monetary cell is a hard error;
- invalid, non-finite, or negative source revenue/refund values are hard errors;
- calculations use `Decimal`, not binary floating point;
- formulas are accepted only when the workbook contains a saved calculated
  value; a formula without a cached result is a hard error;
- multiple shifts or cash registers opened on the same date are summed before
  daily net values are calculated;
- daily records are sorted chronologically.

If aggregated refund exceeds aggregated revenue for card or cash, the negative
net value is retained. Export continues and the web interface displays a warning
with date, revenue, refund, and result.

## 5. Bank normalization

Every bank adapter maps a source row to the same `BankTransaction` model:

- source filename and original row number;
- transaction date and bank;
- statement account and currency;
- document number;
- debit and credit;
- counterparty name, account, and optional tax ID;
- payment purpose.

Exactly one of debit or credit must be positive. Both sides positive, both sides
zero, and invalid internal monetary values are rejected.

Statement accounts must be valid Ukrainian IBANs. Monobank and A-Bank fields
explicitly described as counterparty IBANs are validated the same way. PUMB
`KOR_ACC` and PrivatBank correspondent-account fields may contain a bank-specific
non-IBAN identifier; a value beginning with `UA` must still pass full Ukrainian
IBAN validation.

| Bank | Expected export | Parser behavior |
| --- | --- | --- |
| PUMB | semicolon CSV, CP1251 | `ST_DATE` uses Y.M.D; numeric currency codes map to ISO codes; debit and credit are separate |
| PrivatBank | semicolon CSV, CP1251 | positive signed amount becomes credit; negative signed amount becomes debit |
| Monobank | semicolon CSV, UTF-8 BOM | direction and signed amount must agree; statement IBAN is supplied separately |
| A-Bank | comma CSV, UTF-8 BOM | statement IBAN and currency are extracted from the first metadata row |
| Sense Bank | semicolon CSV, CP1251 | `Кредит` is incoming and `Дебет` is outgoing; extra unescaped semicolons are reconstructed inside `Призначення платежу` |

The strict CSV reader rejects:

- missing or duplicate headers;
- empty statements;
- a non-empty row with a different column count from the header;
- invalid encoding, dates, directions, accounts, or monetary values;
- required parser fields that are blank.

After parsing, any transaction whose currency is not UAH stops the entire run.

## 6. Duplicate protection

Duplicate protection has two levels.

### Identical statement files

Each uploaded statement is hashed with SHA-256 before parsing. If two files have
identical bytes, the request is rejected and both original filenames are shown.

### Overlapping transactions

A parsed transaction with a non-empty document number is considered a duplicate
when this normalized key was already seen:

```text
(
    bank,
    statement account,
    currency,
    transaction date,
    document number,
    debit,
    credit,
    counterparty account,
)
```

The first occurrence is retained; later matches are skipped and recorded as
duplicates. Rows without a document number are not automatically deduplicated
because the remaining fields are insufficient for a safe decision. Such credits
will subsequently be sent to manual review by the classification rules.

## 7. Bank transaction classification

Classification is deterministic. The first matching rule wins.

### 7.1 Debit

```text
debit > 0
-> EXCLUDED: debit transaction
```

Debit exclusion runs before the missing-field rule because outgoing payments
never contribute to income.

### 7.2 Missing credit fields

An incoming transaction requires all five review fields:

- document number;
- counterparty name;
- counterparty account;
- counterparty tax ID;
- payment purpose.

If any are missing:

```text
-> NEEDS_REVIEW: required review fields are missing
```

All missing fields are retained in the classified record so the review page can
name them explicitly.

### 7.3 Conflicting counterparty identity

After all review fields are present, a populated foreign tax ID conflicts with
the client profile when either of these also matches the client:

- counterparty account is in `own_accounts`;
- normalized counterparty name exactly matches `legal_name` or an alias.

```text
foreign tax ID + own account/name
-> NEEDS_REVIEW: counterparty identity conflicts with client profile
```

An unknown account paired with the client's tax ID is not a conflict because
the optional own-account list may be incomplete.

### 7.4 Known own account

```text
counterparty account in own_accounts
-> OWN_TRANSFER
```

### 7.5 Matching client tax ID

```text
counterparty tax ID == client tax ID after digit normalization
-> OWN_TRANSFER
```

### 7.6 Matching client name

```text
counterparty name == legal_name or configured alias after normalization
-> OWN_TRANSFER
```

### 7.7 Excluded payment purpose

Payment purposes are case-insensitive; hyphens are treated as spaces and
repeated whitespace is collapsed.

| Phrase family | Result |
| --- | --- |
| `повернення` / `повернення коштів` | EXCLUDED: refund |
| `поворотна фінансова допомога` | EXCLUDED: returnable financial assistance |
| `поворотно фінансова допомога` | EXCLUDED: returnable financial assistance |
| `гривні від продажу` | EXCLUDED: currency-sale proceeds |

The phrase may appear inside a longer payment purpose.

### 7.8 Eligible credit

Any remaining validated credit is classified as:

```text
-> INCOME: eligible incoming payment
```

Only `INCOME` records contribute to bank income totals.

## 8. Manual-review gate

If at least one transaction is classified as `NEEDS_REVIEW`, export is blocked.
The web application returns a review page rather than a workbook. For every
affected transaction it shows:

- original filename, bank, and CSV row;
- date, amount, and document number;
- counterparty name, account, and tax ID;
- payment purpose;
- reason and specific missing fields.

The employee must correct or re-export the source data and start a new run.
There is no web override that silently forces an unresolved credit into or out
of income.

## 9. Period validation and daily aggregation

The period check considers parsed bank credits and every parsed Checkbox row.
Outgoing debits are ignored for period detection. All detected year-month pairs
must be identical.

After classification succeeds:

1. Only eligible bank credits are summed by transaction date.
2. Checkbox rows are aggregated by opening date.
3. The union of Checkbox and bank dates is processed chronologically.

For each date:

```text
total_income = checkbox_card_net + checkbox_cash_net + eligible_bank_income
```

A missing source component is treated as zero. A date is omitted only when all
three components are individually zero. If components offset each other and the
combined total equals zero, the row is retained because its source breakdown is
not empty.

If no daily entries remain, the exporter saves an unchanged copy of the template
and the web interface reports `Доходів не знайдено` after downloading it.

## 10. Income-book mapping

Official columns:

| Column | Current implementation |
| --- | --- |
| A | Income date |
| B | Stable numeric `total_income` |
| C | Numeric `0.00` |
| D | Formula `=B[row]-C[row]` |
| E | Numeric `0.00` |
| F | Formula `=D[row]+E[row]` |
| G | Numeric `0.00` |
| H | Numeric `0.00` |
| I | Value cleared and style reset to `Normal` |

Column B is deliberately independent from helper formulas. Deleting helper
columns therefore does not break the official income value.

Default helper mapping:

| Column | Current implementation |
| --- | --- |
| J | Formula: card net + cash net + eligible bank income |
| K | Checkbox card net |
| L | Checkbox cash net |
| M | Eligible bank income |

The user may assign these four values to any four unique columns from J through
O. Repeated assignments and numbers outside 10 through 15 are rejected. Values
in unselected helper columns J-O are cleared on rows written by the exporter.

## 11. Existing rows and appending a month

The source template and output path must differ. The uploaded workbook is never
overwritten.

### Updating dates already present

If every generated date already exists in column A, the exporter writes the new
daily values into those rows. Other workbook content is preserved. Existing
summary rows are not relocated.

### Appending a later month

Missing dates may be inserted only when they all belong to one month later than
the latest date already present in the template. The template must provide:

- at least one dated row whose style can be copied;
- existing monthly total rows for every earlier month that contains dated data;
- an exact year-total label `Всього YYYY рік:`.

New daily rows are inserted immediately before the year-total row. Days whose
three source components are all zero were already omitted during aggregation.

The exporter then creates:

1. `Всього <місяць>:` after the new daily rows;
2. `Всього <quarter> кв <year>:` when the new month is March, June, September,
   or December;
3. `Всього 1 півріччя <year>:` after June;
4. an updated `Всього <year> рік:` row.

Monthly totals sum the actual first and last inserted daily rows. Quarter,
half-year, and year totals add the actual monthly-total cell addresses found in
the workbook. They never use fixed offsets or assume that every month contains
the same number of rows.

If an existing month has dated data but no recognizable total row, processing
stops. If more than one total row is found for the same month, processing also
stops. A recognizable month label is normalized to the canonical form
`Всього <місяць>:`; this repairs harmless prefix misspellings while still
requiring an unambiguous month.

Official and selected helper summary cells receive formulas. Unselected helper
values are cleared, selected helper totals receive a full border grid, and the
reserved I cell is cleared without carrying the yellow summary style.

## 12. Formula calculation behavior

`openpyxl` writes Excel formulas but does not execute Microsoft Excel's
calculation engine. Therefore:

- stable numeric source values such as official column B and helper components
  are stored immediately;
- D, F, helper-total, and period-total cells contain real formulas;
- Microsoft Excel recalculates those formulas when editing is enabled;
- Excel Protected View may initially display blank cached formula results until
  the employee clicks `Enable Editing` and recalculation occurs.

This display behavior does not mean the formulas are missing from the workbook.

## 13. Outcome severity

### Hard error: no workbook

Examples include malformed files, missing required values, invalid IBAN or
currency, mixed months, duplicate statement files, invalid helper mapping,
missing worksheet/template structure, and unresolved bank credits.

### Warning: workbook is generated

- Checkbox daily refund exceeds revenue: the negative result is retained and
  shown for manual verification.
- No income is found: an unchanged copy is downloaded and the employee is asked
  to verify the selected files.

### Informational result

Overlapping transaction duplicates are skipped after the first occurrence and
recorded in pipeline response metadata.

## 14. Privacy and deployment boundaries

- Real source documents and client profiles stay outside Git.
- Client YAML files are mounted read-only into the Docker container.
- Uploaded files are temporary and generated workbooks are returned directly.
- The infrastructure reverse proxy provides HTTPS and reaches FastAPI through
  the VM's private address and port 8000.
- HTTPS encrypts traffic but does not authenticate users. Until application
  authentication is implemented, network and firewall controls define who may
  access the service.
