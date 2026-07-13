"""
Usage / activity log for MM Validator.

Records one row per validation session: who ran it, when, how many materials
were validated, AI tokens consumed and the estimated cost. Surfaced to the
admin user via GET /api/admin/usage (Usage Dashboard).

Storage:
  - Default: a local SQLite file (backend/data/usage.db). Zero setup, works
    everywhere — but on Render's free tier the filesystem is EPHEMERAL, so
    the log resets on every deploy/restart.
  - Durable: set the DATABASE_URL env var to any SQLAlchemy-compatible URL
    (e.g. a free Postgres from Neon/Supabase/Render) and the same code uses
    it instead. postgres:// URLs are normalised to postgresql:// for
    SQLAlchemy.

Cost model:
  Prices are USD per 1 million tokens (input, output). Defaults below can be
  overridden (or extended) without a code change via the AI_PRICING_JSON env
  var, e.g.:  AI_PRICING_JSON={"gpt-5.4": [1.25, 10.0]}
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    select,
)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")

_url = os.getenv("DATABASE_URL", "").strip()
if _url.startswith("postgres://"):  # Render/Heroku style → SQLAlchemy style
    _url = "postgresql://" + _url[len("postgres://"):]
if not _url:
    os.makedirs(_DATA_DIR, exist_ok=True)
    _url = f"sqlite:///{os.path.join(_DATA_DIR, 'usage.db')}"

_engine = create_engine(
    _url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {},
)

_metadata = MetaData()

usage_sessions = Table(
    "usage_sessions",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False, index=True),
    Column("role", String(16), nullable=False, default="user"),
    # Stored as naive UTC on every backend for consistent comparisons.
    Column("started_at", DateTime(), nullable=False, index=True),
    Column("file_name", String(255), nullable=False, default=""),
    Column("materials", Integer, nullable=False, default=0),
    Column("errors", Integer, nullable=False, default=0),
    Column("warnings", Integer, nullable=False, default=0),
    Column("infos", Integer, nullable=False, default=0),
    Column("ai_used", Boolean, nullable=False, default=False),
    Column("provider", String(32), nullable=False, default=""),
    Column("model", String(64), nullable=False, default=""),
    Column("ai_calls", Integer, nullable=False, default=0),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_usd", Float, nullable=False, default=0.0),
    Column("duration_ms", Integer, nullable=False, default=0),
    Column("readiness_score", Integer, nullable=True),
    Column("status", String(16), nullable=False, default="success"),
    Column("error", String(500), nullable=False, default=""),
)

_metadata.create_all(_engine)

# Micro-migration: create_all() doesn't alter existing tables, so add columns
# introduced after the first deployment if they're missing.
def _ensure_columns() -> None:
    from sqlalchemy import inspect, text
    try:
        existing = {c["name"] for c in inspect(_engine).get_columns("usage_sessions")}
        with _engine.begin() as conn:
            if "readiness_score" not in existing:
                conn.execute(text(
                    "ALTER TABLE usage_sessions ADD COLUMN readiness_score INTEGER"))
    except Exception:  # noqa: BLE001 — a failed migration must not block startup
        pass


_ensure_columns()


def storage_info() -> dict:
    """Describe where the log lives (shown on the admin dashboard)."""
    if _url.startswith("sqlite"):
        return {
            "backend": "sqlite",
            "durable": False,
            "note": ("Log is stored in a local SQLite file. On Render's free tier "
                     "this resets on every deploy/restart — set DATABASE_URL to a "
                     "free Postgres (Neon/Supabase/Render) to make it permanent."),
        }
    return {"backend": _engine.dialect.name, "durable": True, "note": ""}


# ---------------------------------------------------------------------------
# Cost estimation — USD per 1M tokens: (input, output)
# ---------------------------------------------------------------------------

_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic (per platform.claude.com pricing)
    "claude-haiku-4-5":  (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5":   (3.00, 15.00),
    "claude-opus-4-8":   (5.00, 25.00),
    # OpenAI — VERIFY against openai.com/pricing and override via
    # AI_PRICING_JSON if these drift.
    "gpt-5.4":           (1.25, 10.00),
    "gpt-4o":            (2.50, 10.00),
    "gpt-4o-mini":       (0.15, 0.60),
}


def _pricing() -> dict[str, tuple[float, float]]:
    table = dict(_DEFAULT_PRICING)
    raw = os.getenv("AI_PRICING_JSON", "").strip()
    if raw:
        try:
            for model, pair in json.loads(raw).items():
                table[model] = (float(pair[0]), float(pair[1]))
        except (ValueError, TypeError, IndexError, KeyError):
            pass  # bad override must never break validation
    return table


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for a session; 0.0 for unknown models."""
    model = (model or "").strip().lower()
    table = _pricing()
    rates = table.get(model)
    if rates is None:  # tolerate dated/suffixed ids, e.g. claude-haiku-4-5-20251001
        for key, pair in table.items():
            if model.startswith(key):
                rates = pair
                break
    if rates is None:
        return 0.0
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


# ---------------------------------------------------------------------------
# Write / read
# ---------------------------------------------------------------------------

def log_session(
    *,
    username: str,
    role: str,
    file_name: str,
    materials: int = 0,
    errors: int = 0,
    warnings: int = 0,
    infos: int = 0,
    ai_used: bool = False,
    provider: str = "",
    model: str = "",
    ai_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    readiness_score: int | None = None,
    status: str = "success",
    error: str = "",
) -> None:
    """Insert one session row. Never raises — logging must not break validation."""
    try:
        cost = estimate_cost(model, input_tokens, output_tokens) if ai_used else 0.0
        with _engine.begin() as conn:
            conn.execute(usage_sessions.insert().values(
                username=username,
                role=role,
                started_at=datetime.now(timezone.utc).replace(tzinfo=None),
                file_name=(file_name or "")[:255],
                materials=materials,
                errors=errors,
                warnings=warnings,
                infos=infos,
                ai_used=ai_used,
                provider=provider or "",
                model=model or "",
                ai_calls=ai_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
                duration_ms=duration_ms,
                readiness_score=readiness_score,
                status=status,
                error=(error or "")[:500],
            ))
    except Exception:  # noqa: BLE001
        pass


def fetch_usage(days: int = 30, limit: int = 500) -> dict:
    """Return sessions (recent first), grand totals and per-user aggregates."""
    t = usage_sessions
    where = []
    if days > 0:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        where.append(t.c.started_at >= since)

    with _engine.connect() as conn:
        rows = conn.execute(
            select(t).where(*where).order_by(t.c.started_at.desc()).limit(limit)
        ).mappings().all()

        totals = conn.execute(
            select(
                func.count().label("sessions"),
                func.coalesce(func.sum(t.c.materials), 0).label("materials"),
                func.coalesce(func.sum(t.c.ai_calls), 0).label("ai_calls"),
                func.coalesce(func.sum(t.c.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(t.c.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(t.c.cost_usd), 0.0).label("cost_usd"),
            ).where(*where)
        ).mappings().one()

        per_user = conn.execute(
            select(
                t.c.username,
                func.count().label("sessions"),
                func.coalesce(func.sum(t.c.materials), 0).label("materials"),
                func.coalesce(func.sum(t.c.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(t.c.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(t.c.cost_usd), 0.0).label("cost_usd"),
                func.max(t.c.started_at).label("last_active"),
            ).where(*where).group_by(t.c.username).order_by(func.count().desc())
        ).mappings().all()

    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else v

    return {
        "days": days,
        "storage": storage_info(),
        "totals": dict(totals),
        "per_user": [
            {**dict(r), "last_active": _iso(r["last_active"])} for r in per_user
        ],
        "sessions": [
            {**dict(r), "started_at": _iso(r["started_at"])} for r in rows
        ],
    }
