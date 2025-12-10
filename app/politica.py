from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/politica", response_class=HTMLResponse)
def politica_privacidade():
    return """
    <html>
        <body>
            <h1>Política de Privacidade</h1>
            <p>Esta é a política de privacidade usada pela plataforma.</p>
        </body>
    </html>
    """
