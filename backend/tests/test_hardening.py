"""Hardening tests: atomic job claiming, queue/upload limits, job ownership,
CSV formula-injection sanitisation, and delete-as-cancel.

Run from the repo root:  python -m pytest backend/tests -q
"""
import threading

import pytest
from fastapi import HTTPException

import jobs
import main


def _submit(username="tester", **kw):
    args = dict(
        username=username, role="user", file_name="t.xlsx",
        file_bytes=b"PK\x03\x04-fake", lookup_bytes=None,
        use_ai=False, provider="anthropic", model="m",
    )
    args.update(kw)
    return jobs.submit_job(**args)


def _cleanup(username):
    for j in jobs.list_jobs(username, limit=1000):
        jobs.delete_job(j["id"])


# ---------------------------------------------------------------------------
# Atomic claiming — the two-workers scenario
# ---------------------------------------------------------------------------

def test_claim_is_atomic_under_concurrency():
    job_id = _submit(username="claimer")
    try:
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()   # maximise contention: all claim at once
            results.append(jobs._claim_job(job_id))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1, "exactly one worker must win the claim"
        assert jobs.get_job(job_id)["status"] == "running"
    finally:
        _cleanup("claimer")


def test_claim_skips_deleted_job():
    job_id = _submit(username="claimer2")
    jobs.delete_job(job_id)
    assert jobs._claim_job(job_id) is False


# ---------------------------------------------------------------------------
# Queue / upload limits
# ---------------------------------------------------------------------------

def test_per_user_queue_cap():
    try:
        for _ in range(jobs.MAX_ACTIVE_JOBS_PER_USER):
            _submit(username="flooder")
        with pytest.raises(jobs.TooManyActiveJobs):
            _submit(username="flooder")
        # another user is unaffected
        _submit(username="innocent")
    finally:
        _cleanup("flooder")
        _cleanup("innocent")


def test_upload_size_limit():
    main.check_upload_size(1024, "small.xlsx")   # under the limit — no raise
    with pytest.raises(HTTPException) as exc:
        main.check_upload_size(main.MAX_UPLOAD_BYTES + 1, "huge.xlsx")
    assert exc.value.status_code == 413


# ---------------------------------------------------------------------------
# Ownership authorization
# ---------------------------------------------------------------------------

def test_job_ownership():
    owner = {"username": "alice", "role": "user"}
    other = {"username": "bob", "role": "user"}
    admin = {"username": "root", "role": "admin"}
    job = {"username": "alice", "status": "done"}

    assert main._authorize_job(job, owner) is job
    assert main._authorize_job(job, admin) is job
    with pytest.raises(HTTPException) as exc:
        main._authorize_job(job, other)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        main._authorize_job(None, owner)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# CSV formula-injection sanitisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("=HYPERLINK(\"http://evil\")", "'=HYPERLINK(\"http://evil\")"),
    ("+1+2", "'+1+2"),
    ("-cmd", "'-cmd"),
    ("@SUM(A1)", "'@SUM(A1)"),
    ("\tX", "'\tX"),
    ("normal description", "normal description"),
    ("", ""),
    (42, 42),
    (None, None),
])
def test_csv_safe(value, expected):
    assert jobs.csv_safe(value) == expected


# ---------------------------------------------------------------------------
# Delete cancels queued work
# ---------------------------------------------------------------------------

def test_delete_removes_row_and_data():
    job_id = _submit(username="deleter")
    assert jobs.get_job(job_id) is not None
    assert jobs.delete_job(job_id) is True
    assert jobs.get_job(job_id) is None
    assert jobs.delete_job(job_id) is False     # second delete is a no-op
