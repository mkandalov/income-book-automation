# Business rules

This document records the deterministic accounting rules implemented by the
project. Column positions refer to a Checkbox Z-report Excel export.

## Checkbox source mapping

| Business value | Checkbox field | Excel column | Zero-based index |
| --- | --- | ---: | ---: |
| Business date | `Дата відкриття` | B | 1 |
| Card revenue | `Виручка безготівка` | Z | 25 |
| Card refunds | `Повернення безготівка` | AA | 26 |
| Cash revenue | `Виручка готівка` | AB | 27 |
| Cash refunds | `Повернення готівка` | AC | 28 |

The business date is the date component of the report-opening timestamp.

## Revenue calculations

```text
card_net = card_revenue - card_refund
cash_net = cash_revenue - cash_refund
total_net = card_net + cash_net
```

- Empty monetary cells are interpreted as zero.
- Monetary calculations use `Decimal`, not binary floating-point arithmetic.
- Source revenue and refund values must be non-negative.
- Zero card or cash revenue is retained because the income book is reviewed
  manually after generation.

## Daily aggregation

More than one shift or cash register can exist on the same date. Records with
the same opening date are combined by summing their four source amounts:

- card revenue;
- card refunds;
- cash revenue;
- cash refunds.

Net values are then calculated from the aggregated source amounts. Final daily
records are sorted chronologically.

## Planned income-book mapping

- Column K: Checkbox card net revenue.
- Column L: Checkbox cash net revenue.
- Column M: eligible incoming bank transfers.

## Planned bank rules

The bank parser will include credit transactions only. It will exclude:

- transfers where the counterparty matches the same sole proprietor;
- transactions whose payment purpose indicates a refund;
- transactions whose payment purpose indicates returnable financial assistance
  (`поворотно-фінансова допомога`);
- debit transactions.

These rules will be implemented and tested when the bank-statement parser is
added.
