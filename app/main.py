from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import importlib
from pathlib import Path

app = FastAPI()

# Mount static files 
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize Jinja2 templates with enable_async=True
templates = Jinja2Templates(directory="templates")
# Enable template includes
templates.env.globals.update({
    'include': templates.env.get_template
})

# Automatically register routes from routes directory
routes_path = Path(__file__).parent / "routes"
for route_file in routes_path.glob("*.py"):
    if route_file.stem != "__init__":
        module_path = f"routes.{route_file.stem}"
        route_module = importlib.import_module(module_path)
        if hasattr(route_module, "router"):
            app.include_router(route_module.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)