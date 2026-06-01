from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")
# Enable template includes
templates.env.globals.update({
    'include': templates.env.get_template
})

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "page_name": "dashboard",
            "page_description": "Welcome to the dashboard! Here you can find an overview of your activities and statistics."
        }
    )