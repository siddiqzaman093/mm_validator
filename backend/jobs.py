"""
Background validation jobs for MM Validator.

Why: a 60k-row validation takes 1-2 minutes (more with AI). Running it inside
one long HTTP request means a dropped network connection, closed laptop or
Render restart loses the result after the work was done. Instead, uploads are
stored as a job row in the database, a single worker thread validates them,
and the result (summary + compressed report + complete findings CSV) is
persisted so the user can log back in later and open it from Past Validations.

Design notes:
  - The job queue IS the database (status column); the in-process queue.Queue
    only wakes the worker. On startup, `recover_stuck_jobs` re-queues anything
    left in queued/running by a previous process — input files are kept in the
    row until the job finishes, so a crashed run can always be re-run.
  - ONE worker thread, sequential on purpose: peak memory for a 100k-row file
    is ~200MB and the Render free tier has 512MB total. Two concurrent big
    files would OOM the instance.
  - Blobs are gzipped; a 6.6MB findings CSV compresses to well under 1MB.
    Input files are cleared as soon as the job finishes.
  - Retention: finished jobs older than RETENTION_DAYS are deleted whenever a
    new job is submitted (no background sweeper needed).
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, LargeBinary, MetaData, String, Table,
    select, update, delete,
)

from usage_log import _engine as engine, log_session  # same DB as the usage log
from validator import run_validation
from validator.report import render_html

RETENTION_DAYS = 30

_metadata = MetaData()

jobs_table = Table(
    "validation_jobs",
    _metadata,
    Column("id", String(32), primary_key=True),
    Column("username", String(64), nullable=False, index=True),
    Column("role", String(16), nullable=False, default="user"),
    Column("file_name", String(255), nullable=False, default=""),
    Column("use_ai", Boolean, nullable=False, default=False),
    Column("provider", String(32), nullable=False, default=""),
    Column("model", String(64), nullable=False, default=""),
    # queued | running | done | failed
    Column("status", String(16), nullable=False, default="queued", index=True),
    Column("created_at", DateTime(), nullable=False, index=True),
    Column("started_at", DateTime(), nullable=True),
    Column("finished_at", DateTime(), nullable=True),
    Column("progress_pct", Integer, nullable=False, default=0),
    Column("progress_stage", String(255), nullable=False, default=""),
    Column("ai_done", Integer, nullable=False, default=0),
    Column("ai_total", Integer, nullable=False, default=0),
    # Inputs — kept until the job finishes so a crashed run can be recovered.
    Column("input_file", LargeBinary, nullable=True),
    Column("lookup_file", LargeBinary, nullable=True),
    # Outputs
    Column("result_json_gz", LargeBinary, nullable=True),
    Column("csv_gz", LargeBinary, nullable=True),
    Column("readiness_score", Integer, nullable=True),
    Column("errors", Integer, nullable=False, default=0),
    Column("warnings", Integer, nullable=False, default=0),
    Column("infos", Integer, nullable=False, default=0),
    Column("findings_total", Integer, nullable=False, default=0),
    Column("rows_total", Integer, nullable=False, default=0),
    Column("materials_total", Integer, nullable=False, default=0),
    Column("ai_calls", Integer, nullable=False, default=0),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("duration_ms", Integer, nullable=False, default=0),
    Column("error", String(1000), nullable=False, default=""),
)

_metadata.create_all(engine)

_CSV_COLS = ["severity", "ai_generated", "category", "sheet", "material",
             "row", "field", "sap_field", "value", "message", "rule_id"]

_wakeups: "queue.Queue[str]" = queue.Queue()
_worker_started = threading.Lock()
_worker_running = False

# Live progress of the job currently being processed, keyed by job id.
# Mirrors what the DB row says but without a query — and main.py merges it
# into the admin "Currently Running" panel.
active_jobs: dict[str, dict] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _gz(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6)


def _gunzip(data: bytes) -> bytes:
    return gzip.decompress(data)


# ---------------------------------------------------------------------------
# Submission / queries (called from request handlers)
# ---------------------------------------------------------------------------

def submit_job(*, username: str, role: str, file_name: str, file_bytes: bytes,
               lookup_bytes: bytes | None, use_ai: bool, provider: str,
               model: str) -> str:
    """Store the job and wake the worker. Returns the job id."""
    job_id = uuid.uuid4().hex
    with engine.begin() as conn:
        # Retention sweep piggybacks on submissions.
        conn.execute(delete(jobs_table).where(
            jobs_table.c.created_at < _utcnow() - timedelta(days=RETENTION_DAYS),
            jobs_table.c.status.in_(("done", "failed")),
        ))
        conn.execute(jobs_table.insert().values(
            id=job_id,
            username=username,
            role=role,
            file_name=(file_name or "")[:255],
            use_ai=use_ai,
            provider=provider,
            model=model,
            status="queued",
            created_at=_utcnow(),
            progress_stage="Waiting in queue…",
            input_file=file_bytes,
            lookup_file=lookup_bytes,
        ))
    _wakeups.put(job_id)
    return job_id


_SUMMARY_COLS = [
    jobs_table.c.id, jobs_table.c.username, jobs_table.c.file_name,
    jobs_table.c.use_ai, jobs_table.c.provider, jobs_table.c.model,
    jobs_table.c.status, jobs_table.c.created_at, jobs_table.c.started_at,
    jobs_table.c.finished_at, jobs_table.c.progress_pct,
    jobs_table.c.progress_stage, jobs_table.c.ai_done, jobs_table.c.ai_total,
    jobs_table.c.readiness_score, jobs_table.c.errors, jobs_table.c.warnings,
    jobs_table.c.infos, jobs_table.c.findings_total, jobs_table.c.rows_total,
    jobs_table.c.materials_total, jobs_table.c.duration_ms, jobs_table.c.error,
]


def _row_to_summary(r) -> dict:
    d = dict(r)
    for k in ("created_at", "started_at", "finished_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    # Overlay live progress for the running job (fresher than the last DB write).
    live = active_jobs.get(d["id"])
    if live:
        d.update({k: live[k] for k in
                  ("progress_pct", "progress_stage", "ai_done", "ai_total")})
    return d


def list_jobs(username: str, *, all_users: bool = False, limit: int = 50) -> list[dict]:
    stmt = select(*_SUMMARY_COLS).order_by(jobs_table.c.created_at.desc()).limit(limit)
    if not all_users:
        stmt = stmt.where(jobs_table.c.username == username)
    with engine.connect() as conn:
        return [_row_to_summary(r) for r in conn.execute(stmt).mappings().all()]


def get_job(job_id: str) -> dict | None:
    with engine.connect() as conn:
        r = conn.execute(
            select(*_SUMMARY_COLS).where(jobs_table.c.id == job_id)
        ).mappings().first()
    return _row_to_summary(r) if r else None


def get_job_result(job_id: str) -> bytes | None:
    """The stored result as raw (uncompressed) JSON bytes, or None."""
    with engine.connect() as conn:
        r = conn.execute(
            select(jobs_table.c.result_json_gz).where(jobs_table.c.id == job_id)
        ).first()
    return _gunzip(r[0]) if r and r[0] else None


def get_job_csv(job_id: str) -> bytes | None:
    """The complete findings CSV (uncompressed), or None."""
    with engine.connect() as conn:
        r = conn.execute(
            select(jobs_table.c.csv_gz).where(jobs_table.c.id == job_id)
        ).first()
    return _gunzip(r[0]) if r and r[0] else None


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def start_worker() -> None:
    """Start the single worker thread (idempotent) and recover stuck jobs."""
    global _worker_running
    with _worker_started:
        if _worker_running:
            return
        _worker_running = True
    threading.Thread(target=_worker_loop, name="job-worker", daemon=True).start()
    recover_stuck_jobs()


def recover_stuck_jobs() -> None:
    """Re-queue jobs a previous process left in queued/running.

    Their input files are still in the row, so they simply run again. Jobs
    whose inputs were already cleared (shouldn't happen) are failed cleanly.
    """
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                select(jobs_table.c.id, jobs_table.c.input_file.isnot(None).label("has_input"))
                .where(jobs_table.c.status.in_(("queued", "running")))
                .order_by(jobs_table.c.created_at)
            ).all()
            for job_id, has_input in rows:
                if has_input:
                    conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
                        status="queued", progress_pct=0,
                        progress_stage="Re-queued after server restart…",
                    ))
                else:
                    conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
                        status="failed", finished_at=_utcnow(),
                        error="Server restarted and the uploaded file was no longer available.",
                    ))
        for job_id, has_input in rows:
            if has_input:
                _wakeups.put(job_id)
    except Exception:  # noqa: BLE001 — recovery must never block startup
        pass


def _worker_loop() -> None:
    while True:
        job_id = _wakeups.get()
        try:
            _run_job(job_id)
        except Exception as exc:  # noqa: BLE001 — worker must survive anything
            try:
                with engine.begin() as conn:
                    conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
                        status="failed", finished_at=_utcnow(),
                        error=str(exc)[:1000], input_file=None, lookup_file=None,
                    ))
            except Exception:
                pass
        finally:
            active_jobs.pop(job_id, None)


def _run_job(job_id: str) -> None:
    import os

    with engine.connect() as conn:
        row = conn.execute(
            select(jobs_table).where(jobs_table.c.id == job_id)
        ).mappings().first()
    if not row or row["status"] not in ("queued",):
        return  # already handled (e.g. double wakeup after recovery)
    if not row["input_file"]:
        return

    started = time.monotonic()
    with engine.begin() as conn:
        conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
            status="running", started_at=_utcnow(),
            progress_pct=0, progress_stage="Starting…",
        ))

    live = {
        "username": row["username"], "file_name": row["file_name"],
        "ai_enabled": row["use_ai"], "started_ts": time.time(),
        "progress_pct": 0, "progress_stage": "Starting…",
        "ai_done": 0, "ai_total": 0,
    }
    active_jobs[job_id] = live

    # DB progress writes are throttled; `live` is always current.
    last_write = 0.0

    def _flush(force: bool = False) -> None:
        nonlocal last_write
        now = time.monotonic()
        if not force and now - last_write < 2.0:
            return
        last_write = now
        try:
            with engine.begin() as conn:
                conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
                    progress_pct=live["progress_pct"],
                    progress_stage=live["progress_stage"][:255],
                    ai_done=live["ai_done"], ai_total=live["ai_total"],
                ))
        except Exception:  # noqa: BLE001 — progress writes are best-effort
            pass

    def _on_progress(pct: int, msg: str) -> None:
        live["progress_pct"] = pct
        live["progress_stage"] = msg
        _flush()

    def _on_ai_progress(done: int, total: int) -> None:
        live["ai_done"] = done
        live["ai_total"] = total
        _flush()

    env_var = "OPENAI_API_KEY" if row["provider"] == "openai" else "ANTHROPIC_API_KEY"
    api_key = os.environ.get(env_var, "").strip()
    ai_enabled = bool(row["use_ai"]) and bool(api_key)
    live["ai_enabled"] = ai_enabled

    try:
        report = run_validation(
            bytes(row["input_file"]),
            file_name=row["file_name"],
            lookup_bytes=bytes(row["lookup_file"]) if row["lookup_file"] else None,
            use_ai=ai_enabled,
            api_key=api_key or None,
            model=row["model"],
            provider=row["provider"],
            progress_callback=_on_progress,
            ai_progress_callback=_on_ai_progress,
        )
    except Exception as exc:  # noqa: BLE001
        log_session(
            username=row["username"], role=row["role"], file_name=row["file_name"],
            ai_used=ai_enabled, provider=row["provider"], model=row["model"],
            duration_ms=int((time.monotonic() - started) * 1000),
            status="error", error=str(exc),
        )
        with engine.begin() as conn:
            conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
                status="failed", finished_at=_utcnow(),
                error=str(exc)[:1000], input_file=None, lookup_file=None,
            ))
        return

    live["progress_stage"] = "Storing results…"
    _flush(force=True)

    counts = report.counts()
    readiness = report.readiness()

    result = report.to_dict()          # capped findings, errors first
    result["html_report"] = render_html(report)
    result["job_id"] = job_id          # lets the frontend fetch the full CSV
    result_gz = _gz(json.dumps(result).encode("utf-8"))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLS)
    for f in report.findings:
        d = f.to_dict()
        writer.writerow(["" if d.get(c) is None else d.get(c) for c in _CSV_COLS])
    # utf-8-sig so Excel renders Arabic/non-Latin text correctly on open.
    csv_gz = _gz(buf.getvalue().encode("utf-8-sig"))

    duration_ms = int((time.monotonic() - started) * 1000)
    with engine.begin() as conn:
        conn.execute(update(jobs_table).where(jobs_table.c.id == job_id).values(
            status="done", finished_at=_utcnow(),
            progress_pct=100, progress_stage="Complete",
            result_json_gz=result_gz, csv_gz=csv_gz,
            readiness_score=readiness["score"],
            errors=counts.get("error", 0),
            warnings=counts.get("warning", 0),
            infos=counts.get("info", 0),
            findings_total=len(report.findings),
            rows_total=report.rows_total,
            materials_total=report.materials_total,
            ai_calls=report.ai_calls,
            input_tokens=report.ai_input_tokens,
            output_tokens=report.ai_output_tokens,
            duration_ms=duration_ms,
            input_file=None, lookup_file=None,   # inputs no longer needed
        ))

    log_session(
        username=row["username"], role=row["role"], file_name=row["file_name"],
        materials=report.materials_total or report.rows_total,
        errors=counts.get("error", 0), warnings=counts.get("warning", 0),
        infos=counts.get("info", 0),
        ai_used=ai_enabled, provider=row["provider"], model=row["model"],
        ai_calls=report.ai_calls, input_tokens=report.ai_input_tokens,
        output_tokens=report.ai_output_tokens,
        duration_ms=duration_ms, readiness_score=readiness["score"],
    )
