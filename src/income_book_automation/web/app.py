from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from income_book_automation.config import ClientConfigError
from income_book_automation.exporters.income_book import (
    HelperColumnMapping,
    IncomeBookExportError,
)
from income_book_automation.models import BankName
from income_book_automation.parsers.checkbox import CheckboxParseError
from income_book_automation.parsers.errors import (
    BankStatementParseError,
)
from income_book_automation.pipeline import IncomeBookPipelineError
from income_book_automation.web.processing import (
    UploadInputError,
    generate_income_book_from_uploads,
)

WEB_DIRECTORY = Path(__file__).parent

templates = Jinja2Templates(directory=WEB_DIRECTORY / "templates")

app = FastAPI(
    title="Income Book Automation",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "page_title": "Income Book Automation",
            "banks": tuple(BankName),
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


@app.post("/generate")
def generate_income_book(
    request: Request,
    config_file: Annotated[UploadFile, File()],
    banks: Annotated[list[BankName], Form()],
    bank_statements: Annotated[list[UploadFile], File()],
    account_numbers: Annotated[list[str], Form()],
    checkbox_report: Annotated[UploadFile, File()],
    template_file: Annotated[UploadFile, File()],
    sheet_name: Annotated[str, Form()],
    output_filename: Annotated[str, Form()],
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
            config_file=config_file,
            banks=banks,
            bank_statements=bank_statements,
            account_numbers=account_numbers,
            checkbox_report=checkbox_report,
            template_file=template_file,
            sheet_name=sheet_name,
            helper_columns=helper_columns,
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
        },
    )
