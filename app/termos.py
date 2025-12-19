from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/termos", response_class=HTMLResponse)
async def termos(request: Request):
    return templates.TemplateResponse("termos.html", {"request": request})
