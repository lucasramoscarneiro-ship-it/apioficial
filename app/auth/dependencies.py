from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.db import get_conn
import os

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

SECRET_KEY = os.getenv("JWT_SECRET", "SUPER_SECRET_KEY")
ALGORITHM = "HS256"

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, email, role FROM users WHERE id = %s AND is_active = true",
            (user_id,)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")

        return user

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
