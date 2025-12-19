from fastapi import APIRouter, HTTPException, Query
from psycopg2.extras import RealDictCursor
import os

from app.db import get_conn
from .schemas import LoginRequest, TokenResponse
from .auth_utils import verify_password, create_access_token, hash_password

router = APIRouter(prefix="/api/auth", tags=["Auth"])

SEED_SECRET = os.getenv("SEED_SECRET", "seed-local")


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        "SELECT id, email, password_hash, is_active FROM users WHERE email=%s LIMIT 1",
        (payload.email.lower().strip(),)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    # usuário inexistente ou inativo
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    # hash inválido / antigo (bcrypt etc) -> não deixa dar 500
    try:
        ok = verify_password(payload.password, user["password_hash"])
    except Exception:
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    if not ok:
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    token = create_access_token({"sub": str(user["id"])})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/seed-admin")
async def seed_admin(
    secret: str = Query(...),
    email: str = Query("admin@painel.com"),
    password: str = Query("123456"),
    name: str = Query("Admin"),
    phone_number_id: str = Query(None),
):
    """
    Cria/atualiza um usuário admin de teste.
    Ex:
    POST /api/auth/seed-admin?secret=seed-local&email=admin@painel.com&password=123456
    """
    if secret != SEED_SECRET:
        raise HTTPException(status_code=403, detail="Secret inválido")

    email_clean = email.lower().strip()
    pwd_hash = hash_password(password)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # existe?
    cur.execute("SELECT id FROM users WHERE email=%s", (email_clean,))
    row = cur.fetchone()

    if row:
        cur.execute("""
            UPDATE users
            SET name=%s,
                password_hash=%s,
                role='admin',
                is_active=true,
                phone_number_id = COALESCE(%s, phone_number_id)
            WHERE email=%s
            RETURNING id
        """, (name, pwd_hash, phone_number_id, email_clean))
        user_id = cur.fetchone()["id"]
        status = "updated"
    else:
        cur.execute("""
            INSERT INTO users (name, email, password_hash, role, is_active, phone_number_id)
            VALUES (%s, %s, %s, 'admin', true, %s)
            RETURNING id
        """, (name, email_clean, pwd_hash, phone_number_id))
        user_id = cur.fetchone()["id"]
        status = "created"

    conn.commit()
    cur.close()
    conn.close()

    return {"status": status, "user_id": str(user_id), "email": email_clean, "password": password}
