from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt
from app.core.config import settings
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
def hash_password(password: str) -> str: return pwd_context.hash(password)
def verify_password(password: str, hashed: str) -> bool: return pwd_context.verify(password, hashed)
def create_token(subject: str, token_type: str, expires: timedelta) -> str:
    return jwt.encode({"sub": subject, "type": token_type, "exp": datetime.now(timezone.utc)+expires}, settings.secret_key, algorithm=ALGORITHM)
def create_access_token(subject: str) -> str: return create_token(subject, "access", timedelta(minutes=settings.access_token_minutes))
def create_refresh_token(subject: str) -> str: return create_token(subject, "refresh", timedelta(days=settings.refresh_token_days))
def decode_token(token: str) -> dict: return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
