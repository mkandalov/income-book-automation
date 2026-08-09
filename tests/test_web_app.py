from fastapi.testclient import TestClient
from httpx2 import Response
from pytest import MonkeyPatch

from income_book_automation.web.app import app
from income_book_automation.web.processing import (
    UploadInputError,
    WebGenerationResult,
)

client = TestClient(app)


def _post_generate() -> Response:
    return client.post(
        "/generate",
        data={
            "banks": ["pumb"],
            "account_numbers": [""],
            "sheet_name": "2026",
        },
        files=[
            (
                "config_file",
                ("client.yaml", b"synthetic-config", "application/yaml"),
            ),
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
                    "template.xlsx",
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


def test_index_returns_html_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Формування книги доходів" in response.text


def test_generate_returns_downloadable_excel(
    monkeypatch: MonkeyPatch,
) -> None:
    expected_content = b"synthetic-generated-excel"

    def fake_generate(**_: object) -> WebGenerationResult:
        return WebGenerationResult(
            content=expected_content,
            processed_days=3,
            bank_transactions=10,
            needs_review=1,
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
        'attachment; filename="income-book-result.xlsx"'
    )
    assert response.headers["x-processed-days"] == "3"
    assert response.headers["x-bank-transactions"] == "10"
    assert response.headers["x-needs-review"] == "1"
    assert response.headers["x-duplicates-skipped"] == "2"


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
