import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import quote

from fastapi.testclient import TestClient
from httpx2 import Response
from pytest import LogCaptureFixture, MonkeyPatch

import income_book_automation.web.app as web_app
from income_book_automation.config import ClientProfileOption
from income_book_automation.exporters.income_book import HelperColumnMapping
from income_book_automation.models import (
    CheckboxPaymentMethod,
    CheckboxRefundWarning,
)
from income_book_automation.pipeline import UnresolvedTransactionsError
from income_book_automation.web.processing import (
    ReviewTransactionRow,
    UploadInputError,
    WebGenerationResult,
)

client = TestClient(web_app.app)


def _post_generate(
    *,
    output_filename: str = "custom-income-book.xlsx",
    template_filename: str = "template.xlsx",
    helper_total_column: int = 10,
    checkbox_card_column: int = 11,
    checkbox_cash_column: int = 12,
    bank_income_column: int = 13,
) -> Response:
    return client.post(
        "/generate",
        data={
            "client_id": "client-test-001",
            "source_mode": "both",
            "banks": ["pumb"],
            "account_numbers": [""],
            "sheet_name": "2026",
            "output_filename": output_filename,
            "helper_total_column": helper_total_column,
            "checkbox_card_column": checkbox_card_column,
            "checkbox_cash_column": checkbox_cash_column,
            "bank_income_column": bank_income_column,
        },
        files=[
            (
                "bank_statements",
                ("statement.csv", b"synthetic-bank-statement", "text/csv"),
            ),
            (
                "checkbox_report",
                (
                    "checkbox.xlsx",
                    b"synthetic-checkbox",
                    (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                ),
            ),
            (
                "template_file",
                (
                    template_filename,
                    b"synthetic-template",
                    (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                ),
            ),
        ],
    )


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_returns_html_page(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_app,
        "list_client_profile_options",
        lambda _directory: (
            ClientProfileOption(
                client_id="client-test-001",
                display_name="Тестовий Тарас Іванович",
                search_text="Тестовий Тарас Іванович ФОП Тестовий Т.І.",
            ),
        ),
    )
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Формування книги доходів" in response.text
    assert 'name="source_mode"' in response.text
    assert 'value="checkbox_only"' in response.text
    assert 'value="bank_only"' in response.text
    assert "Сенс Банк" in response.text
    assert response.text.count("data-dynamic-section") == 5
    assert 'form.querySelectorAll("[data-dynamic-section]")' in response.text
    assert 'name="output_filename"' in response.text
    assert 'name="helper_total_column"' in response.text
    assert 'name="checkbox_card_column"' in response.text
    assert 'name="checkbox_cash_column"' in response.text
    assert 'name="bank_income_column"' in response.text
    assert 'name="client_id"' in response.text
    assert 'id="client-search"' in response.text
    assert 'role="combobox"' in response.text
    assert 'role="listbox"' in response.text
    assert "Тестовий Тарас Іванович" in response.text
    assert "client-test-001" in response.text
    assert "1234567890" not in response.text
    assert "налаштування профілю зберігаються на сервері" not in response.text
    assert response.text.count('class="clear-file-button"') == 3
    assert response.text.count('class="choose-file-button"') == 3
    assert response.text.count('class="selected-file-name"') == 3
    assert response.text.count('class="file-validation-message"') == 3
    assert "Обрати файл" in response.text
    assert "Файл не вибрано" in response.text
    assert "Оберіть файл." in response.text
    assert "Звіт по Z-звітам Checkbox XLSX" in response.text
    assert 'id="generation-result"' in response.text
    assert 'id="checkbox-warning-list"' in response.text
    assert "x-checkbox-warnings" in response.text
    assert "x-no-income" in response.text
    assert "Книгу сформовано — доходів не знайдено" in response.text
    assert "downloadWorkbook(workbook, filename)" in response.text


def test_generate_returns_downloadable_excel(
    monkeypatch: MonkeyPatch,
) -> None:
    expected_content = b"synthetic-generated-excel"

    def fake_generate(**_: object) -> WebGenerationResult:
        return WebGenerationResult(
            content=expected_content,
            processed_days=3,
            bank_transactions=10,
            needs_review=0,
            duplicate_transactions=2,
        )

    monkeypatch.setattr(
        ("income_book_automation.web.app.generate_income_book_from_uploads"),
        fake_generate,
    )

    response = _post_generate()

    assert response.status_code == 200
    assert response.content == expected_content
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == (
        'attachment; filename="custom-income-book.xlsx"'
    )
    assert response.headers["x-processed-days"] == "3"
    assert response.headers["x-bank-transactions"] == "10"
    assert response.headers["x-needs-review"] == "0"
    assert response.headers["x-duplicates-skipped"] == "2"
    assert response.headers["x-no-income"] == "false"


def test_generate_accepts_checkbox_only_request(monkeypatch: MonkeyPatch) -> None:
    received_modes: list[object] = []

    def fake_generate(**kwargs: object) -> WebGenerationResult:
        received_modes.append(kwargs["source_mode"])
        return WebGenerationResult(
            content=b"checkbox-only",
            processed_days=1,
            bank_transactions=0,
            needs_review=0,
            duplicate_transactions=0,
        )

    monkeypatch.setattr(web_app, "generate_income_book_from_uploads", fake_generate)
    response = client.post(
        "/generate",
        data={
            "client_id": "client-test-001",
            "source_mode": "checkbox_only",
            "sheet_name": "2026",
            "output_filename": "result.xlsx",
        },
        files=[
            (
                "checkbox_report",
                ("checkbox.xlsx", b"checkbox", "application/octet-stream"),
            ),
            (
                "template_file",
                ("template.xlsx", b"template", "application/octet-stream"),
            ),
        ],
    )

    assert response.status_code == 200
    assert received_modes == [web_app.IncomeSourceMode.CHECKBOX_ONLY]


def test_generate_accepts_bank_only_request(monkeypatch: MonkeyPatch) -> None:
    received_checkbox: list[object] = []

    def fake_generate(**kwargs: object) -> WebGenerationResult:
        received_checkbox.append(kwargs["checkbox_report"])
        return WebGenerationResult(
            content=b"bank-only",
            processed_days=1,
            bank_transactions=1,
            needs_review=0,
            duplicate_transactions=0,
        )

    monkeypatch.setattr(web_app, "generate_income_book_from_uploads", fake_generate)
    response = client.post(
        "/generate",
        data={
            "client_id": "client-test-001",
            "source_mode": "bank_only",
            "banks": ["sense"],
            "account_numbers": [""],
            "sheet_name": "2026",
            "output_filename": "result.xlsx",
        },
        files=[
            ("bank_statements", ("sense.csv", b"statement", "text/csv")),
            (
                "template_file",
                ("template.xlsx", b"template", "application/octet-stream"),
            ),
        ],
    )

    assert response.status_code == 200
    assert received_checkbox == [None]


def test_generate_exposes_no_income_warning(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_generate(**_: object) -> WebGenerationResult:
        return WebGenerationResult(
            content=b"unchanged-income-book",
            processed_days=0,
            bank_transactions=2,
            needs_review=0,
            duplicate_transactions=0,
            no_income=True,
        )

    monkeypatch.setattr(
        "income_book_automation.web.app.generate_income_book_from_uploads",
        fake_generate,
    )

    response = _post_generate()

    assert response.status_code == 200
    assert response.content == b"unchanged-income-book"
    assert response.headers["x-no-income"] == "true"


def test_generate_exposes_checkbox_refund_warnings(
    monkeypatch: MonkeyPatch,
) -> None:
    warning = CheckboxRefundWarning(
        date=date(2026, 6, 15),
        payment_method=CheckboxPaymentMethod.CARD,
        revenue=Decimal("5000.00"),
        refund=Decimal("8000.00"),
    )

    def fake_generate(**_: object) -> WebGenerationResult:
        return WebGenerationResult(
            content=b"synthetic-generated-excel",
            processed_days=1,
            bank_transactions=0,
            needs_review=0,
            duplicate_transactions=0,
            checkbox_warnings=(warning,),
        )

    monkeypatch.setattr(
        "income_book_automation.web.app.generate_income_book_from_uploads",
        fake_generate,
    )

    response = _post_generate()

    assert response.status_code == 200
    assert json.loads(response.headers["x-checkbox-warnings"]) == [
        {
            "date": "2026-06-15",
            "payment_method": "card",
            "revenue": "5000.00",
            "refund": "8000.00",
            "result": "-3000.00",
        }
    ]


def test_generate_renders_review_page_and_does_not_download_workbook(
    monkeypatch: MonkeyPatch,
) -> None:
    review_row = ReviewTransactionRow(
        filename="june-pumb.csv",
        bank="ПУМБ",
        row_number=17,
        transaction_date="15.06.2026",
        amount="125.50 UAH",
        document_number="TEST-REVIEW-001",
        counterparty="—",
        counterparty_account="—",
        counterparty_tax_id="—",
        payment_purpose="Оплата за послуги",
        reason="Відсутні обов’язкові реквізити",
        missing_fields=(
            "Контрагент",
            "IBAN контрагента",
            "РНОКПП/ЄДРПОУ контрагента",
        ),
    )

    def fake_generate(**_: object) -> WebGenerationResult:
        raise UnresolvedTransactionsError(())

    def fake_build_review_rows(_records: object) -> tuple[ReviewTransactionRow, ...]:
        return (review_row,)

    monkeypatch.setattr(
        "income_book_automation.web.app.generate_income_book_from_uploads",
        fake_generate,
    )
    monkeypatch.setattr(
        "income_book_automation.web.app.build_review_transaction_rows",
        fake_build_review_rows,
    )

    response = _post_generate()

    assert response.status_code == 422
    assert "text/html" in response.headers["content-type"]
    assert "content-disposition" not in response.headers
    assert "Книгу доходів не сформовано" in response.text
    assert "june-pumb.csv" in response.text
    assert "ПУМБ · рядок 17" in response.text
    assert "125.50 UAH" in response.text
    assert "Відсутні обов’язкові реквізити" in response.text
    assert "Контрагент" in response.text
    assert "IBAN контрагента" in response.text
    assert "РНОКПП/ЄДРПОУ контрагента" in response.text


def test_generate_forwards_custom_helper_columns(
    monkeypatch: MonkeyPatch,
) -> None:
    received_mappings: list[HelperColumnMapping] = []

    def fake_generate(**kwargs: object) -> WebGenerationResult:
        helper_columns = kwargs["helper_columns"]
        assert isinstance(helper_columns, HelperColumnMapping)
        received_mappings.append(helper_columns)

        return WebGenerationResult(
            content=b"synthetic-generated-excel",
            processed_days=1,
            bank_transactions=1,
            needs_review=0,
            duplicate_transactions=0,
        )

    monkeypatch.setattr(
        ("income_book_automation.web.app.generate_income_book_from_uploads"),
        fake_generate,
    )

    response = _post_generate(
        helper_total_column=10,
        checkbox_card_column=12,
        checkbox_cash_column=13,
        bank_income_column=14,
    )

    assert response.status_code == 200
    assert received_mappings == [
        HelperColumnMapping(
            total=10,
            checkbox_card=12,
            checkbox_cash=13,
            bank_income=14,
        )
    ]


def test_generate_rejects_duplicate_helper_columns() -> None:
    response = _post_generate(
        helper_total_column=10,
        checkbox_card_column=10,
    )

    assert response.status_code == 400
    assert "Кожен показник має бути призначений окремій колонці" in response.text


def test_generate_supports_unicode_output_filename(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_generate(**_: object) -> WebGenerationResult:
        return WebGenerationResult(
            content=b"synthetic-generated-excel",
            processed_days=1,
            bank_transactions=1,
            needs_review=0,
            duplicate_transactions=0,
        )

    monkeypatch.setattr(
        ("income_book_automation.web.app.generate_income_book_from_uploads"),
        fake_generate,
    )

    filename = "Книга доходів липень 2026"
    response = _post_generate(output_filename=filename)

    expected_filename = quote(f"{filename}.xlsx", safe="")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{expected_filename}"
    )


def test_generate_returns_bad_request_for_processing_error(
    monkeypatch: MonkeyPatch,
) -> None:
    def fake_generate(**_: object) -> WebGenerationResult:
        raise UploadInputError("Synthetic upload error")

    monkeypatch.setattr(
        ("income_book_automation.web.app.generate_income_book_from_uploads"),
        fake_generate,
    )

    response = _post_generate()

    assert response.status_code == 400
    assert "text/html" in response.headers["content-type"]
    assert "Не вдалося сформувати книгу доходів" in response.text
    assert "Synthetic upload error" in response.text
    assert "Повернутися до форми" in response.text


def test_generate_hides_unexpected_error_details_and_returns_error_code(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    def fake_generate(**_: object) -> WebGenerationResult:
        raise RuntimeError("secret path: /srv/income-book/clients/client.yaml")

    monkeypatch.setattr(web_app, "generate_income_book_from_uploads", fake_generate)
    monkeypatch.setattr(
        web_app,
        "uuid4",
        lambda: SimpleNamespace(hex="abc12345deadbeef"),
    )

    response = _post_generate()

    assert response.status_code == 500
    assert "Код помилки: ABC12345" in response.text
    assert "повідомте цей код адміністратору" in response.text
    assert "/srv/income-book" not in response.text
    assert "client.yaml" not in response.text
    assert "ABC12345" in caplog.text
    assert "/srv/income-book/clients/client.yaml" in caplog.text
