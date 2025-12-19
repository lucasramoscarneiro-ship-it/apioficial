from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/politica", response_class=HTMLResponse)
async def politica(request: Request):
    # Página pública, sem auth, sem JS
    return templates.TemplateResponse("politica.html", {"request": request})
