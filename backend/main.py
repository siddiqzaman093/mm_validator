"""
SAP MM Validator — FastAPI backend.

Endpoints:
  POST /api/auth/login    → { access_token, token_type }
  POST /api/validate      → ValidationReport JSON (includes html_report field)
  GET  /api/health        → { status: "ok" }

This backend imports the *canonical* validator package that lives at the project
root (``mm_validator/validator``), so the web app runs exactly the same checks as
the Streamlit app — including the lookup-file-driven validations and the SAP UoM
master data.
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Import path: make the project-root `validator/` package importable, NOT a
# local fork. The root package (one level above this file) carries the full
# feature set: lookup loaders, SAP UoM master, lookup checks, Arabic-desc check.
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)   # canonical `validator/` wins
if _BACKEND_DIR not in sys.path:
    sys.path.append(_BACKEND_DIR)        # local modules (e.g. `auth`)

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from auth import authenticate, create_token, verify_token
from validator import run_validation
from validator.report import render_html

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SAP MM Validator API",
    description="Validates SAP S/4HANA Material Master migration templates.",
    version="1.1.0",
)

# Allow the React frontend (any origin during dev; restrict in production via
# the ALLOWED_ORIGINS env var, e.g. "https://mmvalidator.example.com")
_allowed = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    user = verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Exchange username + password for a JWT access token (with role)."""
    user = authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
    }


@app.post("/api/validate")
async def validate(
    file: UploadFile = File(..., description="SAP Product Master Creation .xls/.xlsx"),
    lookup_file: UploadFile | None = File(
        None, description="Product Master Lookup File .xlsx (drives mandatory-field, "
                          "type, product-type and plant→profit-center checks)"),
    use_ai: bool = Form(False, description="Enable AI warning flags"),
    api_key: str = Form("", description="AI provider API key (required when use_ai=true)"),
    model: str = Form("claude-haiku-4-5", description="Model id to use"),
    provider: str = Form("anthropic", description="AI provider: 'anthropic' or 'openai'"),
    _user: dict = Depends(get_current_user),
):
    """
    Validate an uploaded SAP migration template.

    Returns the full ValidationReport as JSON, with an extra `html_report`
    field containing the rendered HTML report (for preview / download).
    """
    if not file.filename or not file.filename.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only .xls and .xlsx files are supported.",
        )

    contents = await file.read()

    # Lookup file is optional at the API layer; the UI makes it mandatory.
    lookup_bytes: bytes | None = None
    if lookup_file is not None and lookup_file.filename:
        if not lookup_file.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The lookup file must be a .xlsx file.",
            )
        lookup_bytes = await lookup_file.read()

    provider = (provider or "anthropic").strip().lower()
    if provider not in ("anthropic", "openai"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider must be 'anthropic' or 'openai'.",
        )

    # Resolve the AI key: a key posted by the client wins; otherwise fall back to
    # the server-side environment variable. This is how the deployed app supplies
    # the key without ever shipping it to browsers.
    env_var = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    effective_key = api_key.strip() or os.environ.get(env_var, "").strip()

    try:
        # Run the blocking validation (Excel parsing + any OpenAI call) in a
        # worker thread so it never blocks the event loop — otherwise a single
        # in-flight validation would freeze /api/health and Render would kill the
        # instance (HTTP health check timeout) mid-request.
        report = await run_in_threadpool(
            run_validation,
            contents,
            file_name=file.filename,
            lookup_bytes=lookup_bytes,
            use_ai=use_ai and bool(effective_key),
            api_key=effective_key or None,
            model=model,
            provider=provider,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: {exc}",
        ) from exc

    html = render_html(report)
    result = report.to_dict()
    result["html_report"] = html  # attach rendered HTML for frontend downloads

    return JSONResponse(content=result)
