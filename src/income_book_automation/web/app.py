import json
import logging
import os
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from income_book_automation.config import (
    ClientConfigError,
    list_client_profile_options,
)
from income_book_automation.exporters.income_book import (
    HelperColumnMapping,
    IncomeBookExportError,
)
from income_book_automation.models import BankName, CheckboxRefundWarning
from income_book_automation.parsers.checkbox import CheckboxParseError
from income_book_automation.parsers.errors import (
    BankStatementParseError,
)
from income_book_automation.pipeline import (
    IncomeBookPipelineError,
    UnresolvedTransactionsError,
)
from income_book_automation.web.processing import (
    IncomeSourceMode,
    UploadInputError,
    build_review_transaction_rows,
    generate_income_book_from_uploads,
)

WEB_DIRECTORY = Path(__file__).parent
PROJECT_DIRECTORY = WEB_DIRECTORY.parents[2]
CLIENT_CONFIG_DIRECTORY = Path(
    os.environ.get(
        "INCOME_BOOK_CLIENTS_DIR",
        PROJECT_DIRECTORY / "private_data" / "clients",
    )
)

templates = Jinja2Templates(directory=WEB_DIRECTORY / "templates")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Income Book Automation",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    try:
        clients = list_client_profile_options(CLIENT_CONFIG_DIRECTORY)
        client_catalog_error = None
    except ClientConfigError:
        clients = ()
        client_catalog_error = (
            "Список ФОПів поки недоступний. Зверніться до адміністратора сервісу."
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page_title": "Income Book Automation",
            "banks": tuple(BankName),
            "clients": clients,
            "client_catalog_error": client_catalog_error,
        },
    )


EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DEFAULT_OUTPUT_FILENAME = "income-book-result.xlsx"


def _normalize_output_filename(
    requested_filename: str,
    template_filename: str | None,
) -> str:
    source = requested_filename.strip() or (template_filename or "").strip()
    filename = source.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    filename = "".join(character for character in filename if character.isprintable())
    filename = filename.strip().strip(".")

    if not filename:
        filename = DEFAULT_OUTPUT_FILENAME

    if not filename.casefold().endswith(".xlsx"):
        filename = f"{filename}.xlsx"

    if len(filename) > 180:
        filename = f"{filename[:-5][:175]}.xlsx"

    return filename


def _content_disposition(filename: str) -> str:
    encoded_filename = quote(filename, safe="")

    if encoded_filename == filename:
        return f'attachment; filename="{filename}"'

    return f"attachment; filename*=UTF-8''{encoded_filename}"


def _serialize_checkbox_warnings(
    warnings: tuple[CheckboxRefundWarning, ...],
) -> str:
    return json.dumps(
        [
            {
                "date": warning.date.isoformat(),
                "payment_method": warning.payment_method.value,
                "revenue": str(warning.revenue),
                "refund": str(warning.refund),
                "result": str(warning.result),
            }
            for warning in warnings
        ],
        separators=(",", ":"),
    )


@app.post("/generate")
def generate_income_book(
    request: Request,
    client_id: Annotated[str, Form()],
    source_mode: Annotated[IncomeSourceMode, Form()],
    template_file: Annotated[UploadFile, File()],
    sheet_name: Annotated[str, Form()],
    output_filename: Annotated[str, Form()],
    banks: Annotated[list[BankName] | None, Form()] = None,
    bank_statements: Annotated[list[UploadFile] | None, File()] = None,
    account_numbers: Annotated[list[str] | None, Form()] = None,
    checkbox_report: Annotated[UploadFile | None, File()] = None,
    helper_total_column: Annotated[int, Form()] = 10,
    checkbox_card_column: Annotated[int, Form()] = 11,
    checkbox_cash_column: Annotated[int, Form()] = 12,
    bank_income_column: Annotated[int, Form()] = 13,
) -> Response:
    try:
        helper_columns = HelperColumnMapping(
            total=helper_total_column,
            checkbox_card=checkbox_card_column,
            checkbox_cash=checkbox_cash_column,
            bank_income=bank_income_column,
        )

        result = generate_income_book_from_uploads(
            client_id=client_id,
            client_config_directory=CLIENT_CONFIG_DIRECTORY,
            source_mode=source_mode,
            banks=banks,
            bank_statements=bank_statements,
            account_numbers=account_numbers,
            checkbox_report=checkbox_report,
            template_file=template_file,
            sheet_name=sheet_name,
            helper_columns=helper_columns,
        )
    except UnresolvedTransactionsError as error:
        review_rows = build_review_transaction_rows(error.records)

        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={
                "page_title": "Потрібна ручна перевірка",
                "review_rows": review_rows,
                "review_count": len(review_rows),
            },
            status_code=422,
        )
    except (
        UploadInputError,
        ClientConfigError,
        BankStatementParseError,
        CheckboxParseError,
        IncomeBookExportError,
        IncomeBookPipelineError,
    ) as error:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "page_title": "Помилка обробки",
                "error_message": str(error),
            },
            status_code=400,
        )
    except Exception:
        error_code = uuid4().hex[:8].upper()
        logger.exception(
            "Unexpected income-book generation error [code=%s]",
            error_code,
        )

        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "page_title": "Неочікувана помилка",
                "error_message": (
                    "Сталася неочікувана помилка. "
                    f"Код помилки: {error_code}. Повторіть спробу або "
                    "повідомте цей код адміністратору."
                ),
            },
            status_code=500,
        )

    download_filename = _normalize_output_filename(
        output_filename,
        template_file.filename,
    )

    return Response(
        content=result.content,
        media_type=EXCEL_MEDIA_TYPE,
        headers={
            "Content-Disposition": _content_disposition(download_filename),
            "X-Processed-Days": str(result.processed_days),
            "X-Bank-Transactions": str(result.bank_transactions),
            "X-Needs-Review": str(result.needs_review),
            "X-Duplicates-Skipped": str(result.duplicate_transactions),
            "X-Checkbox-Warnings": _serialize_checkbox_warnings(
                result.checkbox_warnings
            ),
            "X-No-Income": str(result.no_income).lower(),
        },
    )
