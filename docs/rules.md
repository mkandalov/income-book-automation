# Business rules

This document is the deterministic business-rule specification implemented by
Income Book Automation. It describes how source records become daily income-book
entries and makes the application's decisions reviewable without reading the
parser code.

The application assists an accountant; it does not replace the final accounting
review.

## 1. Processing scope

One pipeline run receives:

- one client profile;
- one or more supported bank statement CSV files;
- one Checkbox Z-report workbook;
- one existing income-book XLSX template;
- a target worksheet name;
- an optional mapping for four helper columns.

All generated daily entries must belong to one calendar month. Multiple bank
statements may belong to different supported banks, but each statement must be
paired with the bank format selected by the user.

## 2. Client identity

The client YAML profile contains:

| Field | Required | Purpose |
| --- | --- | --- |
| `client_id` | yes | Internal stable identifier |
| `legal_name` | yes | Detect transfers made under the client's legal name |
| `tax_id` | yes | Detect counterparties with the client's РНОКПП/ЄДРПОУ |
| `own_accounts` | no | Known IBANs belonging to the client |
| `name_aliases` | no | Alternative exact names used in bank statements |

An empty `own_accounts` list is allowed. In that case, own-transfer detection
still uses the tax ID, legal name, and configured aliases.

Before comparison:

- IBAN whitespace is removed and letters are uppercased;
- every configured own IBAN must use the Ukrainian `UA` + 27 digits format and
  pass its ISO 13616 checksum;
- tax IDs are reduced to digits;
- names are case-folded, hyphens become spaces, and repeated whitespace is
  collapsed.

Name matching is exact after normalization; it is not a substring or fuzzy
match.

## 3. Checkbox mapping

Checkbox fields are resolved by normalized header text rather than fixed Excel
positions. This allows the source columns to be reordered.

| Business value | Required Checkbox header |
| --- | --- |
| Business date | `Дата відкриття` |
| Card revenue | `Виручка безготівка` |
| Card refunds | `Повернення безготівка` |
| Cash revenue | `Виручка готівка` |
| Cash refunds | `Повернення готівка` |

The business date is the date component of the report-opening timestamp. A
fully blank row is ignored. A row containing amounts but no opening date is a
hard error.

### Checkbox monetary rules

```text
card_net = card_revenue - card_refund
cash_net = cash_revenue - cash_refund
checkbox_total = card_net + cash_net
```

- Explicit numeric zero is valid; an empty required monetary cell is a hard
  error.
- Text, non-finite values, negative source values, and formulas without a saved
  result are hard errors.
- Source revenue and refund values must be non-negative.
- All monetary calculations use `Decimal`, not binary floating-point numbers.
- Multiple shifts or cash registers opened on the same date are aggregated by
  summing their source revenue and refund values before net totals are used.
- Aggregated dates are sorted chronologically.
- A daily refund greater than its corresponding revenue produces a warning but
  does not block export; the negative net value is retained.

## 4. Bank source normalization

Every supported bank parser maps its source row to the same `BankTransaction`
model:

- transaction date;
- bank;
- statement account;
- currency;
- document number;
- debit and credit;
- counterparty name, account, and optional tax ID;
- payment purpose.

Exactly one of debit or credit must be positive. Negative internal monetary
values and rows with both sides positive or both sides zero are rejected.

Statement accounts must be valid Ukrainian IBANs and pass the ISO 13616
checksum. Monobank and A-Bank fields explicitly labelled as counterparty IBANs
are validated the same way. PUMB `KOR_ACC` and PrivatBank correspondent-account
fields may contain a bank-specific non-IBAN account identifier; values beginning
with `UA` are still required to pass IBAN validation.

| Bank | File format | Parser-specific behavior |
| --- | --- | --- |
| PUMB | semicolon-delimited CSV, CP1251 | Numeric currency codes are mapped to ISO currency codes |
| PrivatBank | semicolon-delimited CSV, CP1251 | Positive signed amounts become credit; negative amounts become debit |
| Monobank | semicolon-delimited CSV, UTF-8 with BOM | Direction is read from the debit/credit field; statement IBAN is supplied by the user |
| A-Bank | comma-delimited CSV, UTF-8 with BOM | Statement IBAN and currency are extracted from the metadata row |

The CSV reader rejects duplicate headers and any non-empty row whose column
count differs from the header. Missing headers, empty statements, invalid
encodings, unsupported directions, invalid dates, invalid account numbers, and
invalid monetary values stop processing with a file-specific error. After
parsing, any transaction whose currency is not UAH stops the entire run.

## 5. Bank transaction classification

Rules are applied in the following order. The first matching rule determines
the category.

### 5.1 Debit transaction

If `debit > 0`:

```text
category = EXCLUDED
reason = debit transaction
```

### 5.2 Missing classification fields

An incoming transaction requires all of the following:

- document number;
- counterparty name;
- counterparty account;
- counterparty tax ID;
- payment purpose.

If at least one is missing:

```text
category = NEEDS_REVIEW
reason = required review fields are missing
```

The transaction is not included, and workbook generation is blocked until the
source data is corrected.

### 5.3 Conflicting counterparty identity

If a populated foreign tax ID is paired with either a configured own account or
an exact client-name match:

```text
category = NEEDS_REVIEW
reason = counterparty identity conflicts with client profile
```

An unknown account is not a conflict when the tax ID matches the client because
the optional `own_accounts` list may be incomplete.

### 5.4 Known own account

If the normalized counterparty IBAN is present in `client.own_accounts`:

```text
category = OWN_TRANSFER
reason = counterparty account belongs to client
```

### 5.5 Matching client tax ID

If both tax IDs are present and the counterparty tax ID equals the client's tax
ID after normalization:

```text
category = OWN_TRANSFER
reason = counterparty tax ID belongs to client
```

### 5.6 Matching client name

If the normalized counterparty name exactly matches `legal_name` or one of
`name_aliases`:

```text
category = OWN_TRANSFER
reason = counterparty name belongs to client
```

### 5.7 Excluded payment purpose

The normalized payment purpose is checked for the following phrases:

| Phrase or phrase family | Classification reason |
| --- | --- |
| `повернення` / `повернення коштів` | Refund |
| `поворотна фінансова допомога` | Returnable financial assistance |
| `поворотно фінансова допомога` | Returnable financial assistance |
| `гривні від продажу` | Currency sale proceeds |

If a phrase is contained in the payment purpose:

```text
category = EXCLUDED
```

Comparison is case-insensitive, treats hyphens as spaces, and collapses repeated
whitespace.

### 5.8 Eligible incoming payment

Any remaining validated credit is classified as:

```text
category = INCOME
reason = eligible incoming payment
```

Only `INCOME` transactions are included in daily bank totals.

## 6. Duplicate handling

Two levels of duplicate protection are applied.

### Identical uploaded files

Each bank statement is hashed with SHA-256. If two uploaded files have identical
content, the pipeline rejects the request and asks the user to remove one file.

### Overlapping statement rows

A transaction with a document number is considered a duplicate when the
following normalized key has already been seen:

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

The first transaction is retained and later matches are reported as skipped
duplicates. Transactions without a document number are retained because the
available data is not sufficient for safe automatic deduplication.

## 7. Daily aggregation and merge

Eligible bank credits are summed by transaction date. The daily bank result is
merged with already aggregated Checkbox data using the union of their dates.

For each date:

```text
total_income = checkbox_card_net + checkbox_cash_net + eligible_bank_income
```

If all three source components are zero, no row is produced for that date. A
date present in only one source is retained, with missing components treated as
zero. Output dates are sorted chronologically.

## 8. Income-book column mapping

The official workbook columns are written as follows:

| Column | Current MVP value |
| --- | --- |
| A | Income date |
| B | Numeric `total_income` value |
| C | `0.00` |
| D | Excel formula `=B[row]-C[row]` |
| E | `0.00` |
| F | Excel formula `=D[row]+E[row]` |
| G | `0.00` |
| H | `0.00` |

Column B contains a stable numeric value rather than a reference to a helper
column. Deleting the helper columns therefore does not break the official
income amount.

The default helper mapping is:

| Column | Value |
| --- | --- |
| J | Formula: Checkbox card + Checkbox cash + eligible bank income |
| K | Checkbox card net income |
| L | Checkbox cash net income |
| M | Eligible bank income |

The user may assign these four values to any four unique columns from J through
O. Assignments outside that range or repeated assignments are rejected.

## 9. Existing dates and new months

The exporter never writes the generated workbook over the source template.

### Dates already present in the template

If every generated date already exists in column A, the exporter updates the
matching rows while preserving the rest of the workbook. Existing template
summary rows and formulas remain in place.

### Appending a later month

Missing dates may be appended only when their single calendar month is later
than the latest date already present in the template. The template must contain:

- at least one existing dated row whose style can be copied;
- at least one existing monthly total row;
- the label `Всього YYYY рік:` for the processed year.

The new daily rows are inserted immediately before the year-total row. The
exporter then:

1. copies the existing daily-row style;
2. writes all non-zero daily entries;
3. adds `Всього <місяць>:`;
4. adds `Всього <quarter> кв <year>:` when the month closes a quarter;
5. adds `Всього 1 півріччя <year>:` after June;
6. recalculates `Всього <year> рік:` from available monthly total rows.

Official totals and configured helper totals use Excel formulas. The style of
summary rows is copied from an existing monthly-total row.

If dates are absent but do not form a later month, the exporter stops instead
of guessing where to place them.

## 10. Web upload rules

- At least one and at most ten bank statements are accepted.
- Each statement must have a selected bank; Monobank statements also require a
  statement IBAN.
- Bank statements must use `.csv`.
- The Checkbox Z-report and income-book template must use `.xlsx`.
- The client profile must use `.yaml` or `.yml`.
- Each upload may be at most 20 MB and must not be empty.
- The target worksheet name must not be blank.
- Original filenames are included in validation messages so the user can locate
  the incorrect upload.

Web uploads are copied into an isolated temporary directory for one request and
removed when processing finishes.

## 11. Manual review and limitations

- The application is deterministic: it does not use an LLM to guess ambiguous
  accounting classifications.
- Transactions classified as `NEEDS_REVIEW` require an accountant's decision.
- The current output does not include a separate downloadable audit report;
  classified and duplicate records are available in the pipeline result.
- Only UAH transactions are accepted. Currency conversion is not performed;
  any other currency blocks workbook generation.
- Own-transfer detection is strongest when the client profile contains current
  tax ID, legal name, aliases, and known own accounts.
- PDF and legacy `.xls` inputs are not supported by the current MVP.
- A single run cannot generate entries for more than one calendar month.
