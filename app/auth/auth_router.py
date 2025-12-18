from fastapi import APIRouter, HTTPException
from app.db import get_conn
from .schemas import LoginRequest, TokenResponse
from .auth_utils import verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, password_hash FROM users WHERE email = %s AND is_active = true",
        (payload.email,)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    token = create_access_token({"sub": str(user["id"])})
    return {"access_token": token}
