import os
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Загрузка статического ключа из переменных окружения (позже можно переделать на БД)
VALID_API_KEY = os.getenv("API_KEY")
if not VALID_API_KEY:
    raise RuntimeError("API_KEY не задан в .env")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API ключ отсутствует. Передайте его в заголовке X-API-Key."
        )
    if api_key != VALID_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Неверный API ключ"
        )
    return api_key
