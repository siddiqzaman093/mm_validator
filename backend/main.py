"""
SAP MM Validator — FastAPI backend.

Endpoints:
  POST   /api/auth/login       → { access_token, token_type }
  POST   /api/jobs             → queue a validation, returns { job_id }
  GET    /api/jobs             → the caller's jobs (admin: ?all=true)
  GET    /api/jobs/{id}        → job status + progress + summary
  GET    /api/jobs/{id}/result → stored ValidationReport JSON (+ html_report)
  GET    /api/jobs/{id}/csv    → complete findings CSV
  DELETE /api/jobs/{id}        → remove a finished/queued job and its data
  GET    /api/admin/usage      → usage log / dashboard data (admin only)
  GET    /api/admin/active     → validations running right now (admin only)
  GET    /api/health           → { status: "ok" }

This backend imports the *canonical* validator package that lives at the project
root (``mm_validator/validator``), so the web app runs exactly the same checks as
the Streamlit app — including the lookup-file-driven validations and the SAP UoM
master data.
"""
from __future__ import annotations

import os
import sys
import time

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
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from auth import authenticate, create_token, verify_token
from usage_log import fetch_usage

import jobs as jobs_mod

# Reject uploads beyond this size before they reach the database — the
# largest real-world Migration Cockpit workbooks seen so far are ~2MB, so
# 25MB leaves generous headroom while keeping the Neon free tier safe.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "") or 25)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SAP MM Validator API",
    description="Validates SAP S/4HANA Material Master migration templates.",
    version="1.1.0",
)

# Allow the React frontend. ALLOWED_ORIGINS lists explicit origins
# (comma-separated); blank/unset falls back to "*" so a wiped env var can't
# take the app down. The regex additionally admits every Vercel deployment of
# the frontend (production, previews, branch URLs), which plain origins miss.
_allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed or ["*"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@app.on_event("startup")
async def _start_job_worker() -> None:
    # Also re-queues jobs a previous process left unfinished (Render restarts).
    jobs_mod.start_worker()

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


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
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
    token = create_token(user["username"], user["role"], user.get("name", ""))
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
        "name": user.get("name", ""),
    }


# ---------------------------------------------------------------------------
# Background validation jobs
# ---------------------------------------------------------------------------

def _authorize_job(job: dict | None, user: dict) -> dict:
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job["username"] != user["username"] and user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your job")
    return job


def check_upload_size(n_bytes: int, filename: str) -> None:
    if n_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"'{filename}' is {n_bytes / 1024 / 1024:.1f}MB — uploads are "
                    f"limited to {MAX_UPLOAD_MB}MB."),
        )


@app.post("/api/jobs")
async def submit_validation_job(
    file: UploadFile = File(...),
    lookup_file: UploadFile | None = File(None),
    use_ai: bool = Form(False),
    model: str = Form("claude-haiku-4-5"),
    provider: str = Form("anthropic"),
    user: dict = Depends(get_current_user),
):
    """Queue a validation and return immediately with a job id.

    The upload is stored in the database, so the result survives dropped
    connections, closed browsers and server restarts.
    """
    if not file.filename or not file.filename.lower().endswith((".xls", ".xlsx")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only .xls and .xlsx files are supported.",
        )
    provider = (provider or "anthropic").strip().lower()
    if provider not in ("anthropic", "openai"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provider must be 'anthropic' or 'openai'.",
        )
    lookup_bytes: bytes | None = None
    if lookup_file is not None and lookup_file.filename:
        if not lookup_file.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The lookup file must be a .xlsx file.",
            )
        lookup_bytes = await lookup_file.read()
        check_upload_size(len(lookup_bytes), lookup_file.filename)

    contents = await file.read()
    check_upload_size(len(contents), file.filename)
    try:
        job_id = await run_in_threadpool(
            jobs_mod.submit_job,
            username=user["username"],
            role=user.get("role", "user"),
            file_name=file.filename,
            file_bytes=contents,
            lookup_bytes=lookup_bytes,
            use_ai=use_ai,
            provider=provider,
            model=model,
        )
    except jobs_mod.TooManyActiveJobs as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc),
        ) from exc
    return {"job_id": job_id}


@app.get("/api/jobs")
async def list_validation_jobs(all: bool = False, user: dict = Depends(get_current_user)):
    """The caller's past/current jobs, newest first. Admins may pass all=true."""
    all_users = bool(all) and user.get("role") == "admin"
    runs = await run_in_threadpool(
        jobs_mod.list_jobs, user["username"], all_users=all_users
    )
    return {"jobs": runs}


@app.get("/api/jobs/{job_id}")
async def get_validation_job(job_id: str, user: dict = Depends(get_current_user)):
    job = _authorize_job(await run_in_threadpool(jobs_mod.get_job, job_id), user)
    return job


@app.get("/api/jobs/{job_id}/result")
async def get_validation_job_result(job_id: str, user: dict = Depends(get_current_user)):
    _authorize_job(await run_in_threadpool(jobs_mod.get_job, job_id), user)
    raw = await run_in_threadpool(jobs_mod.get_job_result, job_id)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result not available (job still running, failed, or expired).",
        )
    return Response(content=raw, media_type="application/json")


@app.get("/api/jobs/{job_id}/csv")
async def get_validation_job_csv(job_id: str, user: dict = Depends(get_current_user)):
    _authorize_job(await run_in_threadpool(jobs_mod.get_job, job_id), user)
    raw = await run_in_threadpool(jobs_mod.get_job_csv, job_id)
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CSV not available (job still running, failed, or expired).",
        )
    return Response(
        content=raw, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="validation-findings.csv"'},
    )


@app.delete("/api/jobs/{job_id}")
async def delete_validation_job(job_id: str, user: dict = Depends(get_current_user)):
    """Remove a job and all its stored data (owner or admin).

    Queued jobs are cancelled; running jobs must finish first — the worker
    would have nowhere to write the result.
    """
    job = _authorize_job(await run_in_threadpool(jobs_mod.get_job, job_id), user)
    if job["status"] == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This validation is currently running — wait for it to finish.",
        )
    await run_in_threadpool(jobs_mod.delete_job, job_id)
    return {"deleted": job_id}


@app.get("/api/admin/usage")
async def admin_usage(days: int = 30, _admin: dict = Depends(require_admin)):
    """Usage log for the admin dashboard. days<=0 returns all history."""
    return await run_in_threadpool(fetch_usage, days=days)


@app.get("/api/admin/active")
async def admin_active_runs(_admin: dict = Depends(require_admin)):
    """Validations running on the server right now (admin only)."""
    now = time.time()
    runs = [
        {
            "username": e["username"],
            "file_name": e["file_name"],
            "ai_enabled": e["ai_enabled"],
            "elapsed_s": int(now - e["started_ts"]),
            "stage": e["progress_stage"],
            "pct": e["progress_pct"],
            "ai_done": e["ai_done"],
            "ai_total": e["ai_total"],
        }
        for e in jobs_mod.active_jobs.values()
    ]
    return {"runs": sorted(runs, key=lambda r: -r["elapsed_s"])}
