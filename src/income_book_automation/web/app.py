from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from income_book_automation.config import ClientConfigError
from income_book_automation.exporters.income_book import (
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
) -> Response:
    try:
        result = generate_income_book_from_uploads(
            config_file=config_file,
            banks=banks,
            bank_statements=bank_statements,
            account_numbers=account_numbers,
            checkbox_report=checkbox_report,
            template_file=template_file,
            sheet_name=sheet_name,
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
    return Response(
        content=result.content,
        media_type=EXCEL_MEDIA_TYPE,
        headers={
            "Content-Disposition": ('attachment; filename="income-book-result.xlsx"'),
            "X-Processed-Days": str(result.processed_days),
            "X-Bank-Transactions": str(result.bank_transactions),
            "X-Needs-Review": str(result.needs_review),
            "X-Duplicates-Skipped": str(result.duplicate_transactions),
        },
    )
