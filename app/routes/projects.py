from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")
# Enable template includes
templates.env.globals.update({
    'include': templates.env.get_template
})

@router.get("/projects", response_class=HTMLResponse)
async def projects(request: Request):
    return templates.TemplateResponse(
        request,
        "projects.html",
        {
            "request": request,
            "page_name": "projects",
            "page_description": "Welcome to the projects page! Here you can find an overview of your projects and their statuses."
        }
    )