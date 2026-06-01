from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env.globals.update({
    'include': templates.env.get_template
})

@router.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    return templates.TemplateResponse(
        request,
        "scan.html",
        {
            "request": request,
            "page_name": "scan",
            "page_title": "Security Scanning",
            "page_description": "Upload projects and manage security scans with Bandit"
        }
    )

@router.get("/results/{scan_id}", response_class=HTMLResponse)
async def results_page(request: Request, scan_id: str):
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "request": request,
            "page_name": "results",
            "page_title": f"Scan Results - {scan_id}",
            "page_description": "Detailed security scan results from Bandit analysis"
        }
    )