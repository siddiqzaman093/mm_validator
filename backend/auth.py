"""
JWT-based authentication for MM Validator API.

Two roles are supported:
  admin — full access, including the Admin Activities (AI configuration and
          Usage Dashboard) panels
  user  — validator only (AI-Enabled Validations toggle); no admin panels visible

Login ids are e-mail addresses (matched case-insensitively), plus the two
built-in accounts `admin` and `mm01`.

Credentials are configured via environment variables (with local-dev defaults):
  MM_PASSWORD     admin's password   (default: admin123)
  MM01_PASSWORD   mm01's password    (default: password123)
  <MAILBOX>_PASSWORD                 (default: password123 each)
                  password for each named user, derived from the mailbox name:
                  siddiq.uzzaman@arete-global.com → SIDDIQ_UZZAMAN_PASSWORD
  JWT_SECRET      token signing key  (default: change-me — set this in production!)
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "CHANGE-ME-IN-PRODUCTION-SET-JWT_SECRET-ENV-VAR")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

# (login id, display name, role) — login ids are stored/matched lowercase
_DIRECTORY: list[tuple[str, str, str]] = [
    ("siddiq.uzzaman@arete-global.com",    "Siddiq Zaman",      "admin"),
    ("ismail.shaik@arete-global.com",      "Ismail Shaik",      "user"),
    ("mohamed.omran@arete-global.com",     "Mohamed Omran",     "user"),
    ("mohamed.osama@arete-global.com",     "Mohamed Osama",     "user"),
    ("yahya.omar@arete-global.com",        "Yahya Omar",        "user"),
    ("mohamed.elewa@arete-global.com",     "Mohamed Elewa",     "user"),
    ("abdelaziz.nassar@arete-global.com",  "Abdelaziz Nassar",  "user"),
    ("abdelrhaman.osama@arete-global.com", "Abdelrahman Osama", "user"),
]


def _env_var_for(login: str) -> str:
    """siddiq.uzzaman@arete-global.com → SIDDIQ_UZZAMAN_PASSWORD"""
    mailbox = login.split("@", 1)[0]
    return re.sub(r"[^A-Z0-9]", "_", mailbox.upper()) + "_PASSWORD"


def _env_password(var: str, default: str) -> str:
    """
    Read a password env var defensively. A Render blueprint sync can (re)create
    sync:false vars with EMPTY values, and copy-paste often adds stray
    whitespace — an empty/blank value would lock the account out entirely, so
    treat it as unset and fall back to the default instead.
    """
    value = (os.getenv(var) or "").strip()
    return value or default


# username (lowercase) -> {password, role, name}
USERS: dict[str, dict[str, str]] = {
    "admin": {
        "password": _env_password("MM_PASSWORD", "admin123"),
        "role": "admin",
        "name": "Administrator",
    },
    "mm01": {
        "password": _env_password("MM01_PASSWORD", "password123"),
        "role": "user",
        "name": "MM01",
    },
}
for _login, _display, _role in _DIRECTORY:
    USERS[_login] = {
        "password": _env_password(_env_var_for(_login), "password123"),
        "role": _role,
        "name": _display,
    }


def authenticate(username: str, password: str) -> dict | None:
    """Return {'username', 'role', 'name'} for valid credentials, else None."""
    username = (username or "").strip().lower()
    user = USERS.get(username)
    if not user or not secrets.compare_digest(password, user["password"]):
        return None
    return {"username": username, "role": user["role"], "name": user["name"]}


def create_token(username: str, role: str, name: str = "") -> str:
    """Return a signed JWT carrying the username, role and display name."""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "role": role, "name": name, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def verify_token(token: str) -> dict | None:
    """Return {'username', 'role', 'name'} from a valid JWT, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return {
        "username": username,
        "role": payload.get("role", "user"),
        "name": payload.get("name", ""),
    }
