import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL_RAW = os.getenv("DATABASE_URL")

if not DATABASE_URL_RAW:
    raise RuntimeError("DATABASE_URL não encontrado no .env")

# Remove qualquer parâmetro sslmode da URL (com ou sem aspas)
if "sslmode=" in DATABASE_URL_RAW:
    # corta no "?" para tirar a query string inteira
    DATABASE_URL = DATABASE_URL_RAW.split("?", 1)[0]
else:
    DATABASE_URL = DATABASE_URL_RAW


def get_conn():
    # força um sslmode válido aqui
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",      # se der problema, pode testar "prefer"
        cursor_factory=RealDictCursor,
    )
