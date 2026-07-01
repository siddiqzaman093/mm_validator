"""
JWT-based authentication for MM Validator API.

Two roles are supported:
  admin — full access, including the Admin Activities (AI provider / key / model) panel
  user  — validator only (AI Warning Flags toggle); no AI configuration visible

Credentials are configured via environment variables (with local-dev defaults):
  MM_PASSWORD    admin's password   (default: admin123)
  MM01_PASSWORD  mm01's password    (default: password1234)
  JWT_SECRET     token signing key  (default: change-me — set this in production!)
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "CHANGE-ME-IN-PRODUCTION-SET-JWT_SECRET-ENV-VAR")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

# username -> {password, role}
USERS: dict[str, dict[str, str]] = {
    "admin": {"password": os.getenv("MM_PASSWORD", "admin123"),       "role": "admin"},
    "mm01":  {"password": os.getenv("MM01_PASSWORD", "password123"), "role": "user"},
}


def authenticate(username: str, password: str) -> dict | None:
    """Return {'username', 'role'} for valid credentials, else None."""
    user = USERS.get(username)
    if not user or not secrets.compare_digest(password, user["password"]):
        return None
    return {"username": username, "role": user["role"]}


def create_token(username: str, role: str) -> str:
    """Return a signed JWT carrying the username and role."""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "role": role, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def verify_token(token: str) -> dict | None:
    """Return {'username', 'role'} from a valid JWT, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return {"username": username, "role": payload.get("role", "user")}
