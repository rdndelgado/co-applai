from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import constants
from services import db, rate_limit
from services.graph import get_graph, run_continue_from_pending, run_manual_redraft
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="co-applai")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local practice project, not public-facing
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_STATUSES = {
    constants.STATUS_APPROVED,
    constants.STATUS_DRAFTED,
    constants.STATUS_REJECTED,
    constants.STATUS_PENDING,
}


class StatusBody(BaseModel):
    status: str
    feedback: str = ""


class FeedbackBody(BaseModel):
    feedback: str = ""


class DraftJobsBody(BaseModel):
    job_ids: List[int]


def _run_job(job_id):
    letter = db.ensure_letter_row(job_id)
    try:
        if letter.get("job_context") and letter.get("fit_assessment"):
            # already went through discovery+matcher before (e.g. a prior
            # failed run) -- redraft only, don't redo them
            run_manual_redraft(
                job_id,
                letter["id"],
                letter["job_context"],
                letter["fit_assessment"],
                letter.get("rejection_feedback"),
            )
        elif letter.get("job_context"):
            # has job_context but never got through matcher (e.g. crashed
            # between discovery and matcher)
            run_continue_from_pending(
                job_id, letter["id"], letter["job_context"], letter.get("rejection_feedback")
            )
        else:
            graph = get_graph()
            config = {"configurable": {"thread_id": str(job_id)}}
            graph.invoke({"job_id": job_id, "letter_id": letter["id"]}, config=config)
    except Exception as exc:
        # mark as rejected (not the default 'drafted') so fetch_unlettered_jobs
        # retries it on the next batch run instead of silently skipping it forever
        db.update_letter(
            letter["id"],
            {"status": constants.STATUS_REJECTED, "rejection_feedback": f"run failed: {exc}"},
        )
        logger.error("job_id=%s run failed: %s", job_id, exc)


def _run_batch_background():
    jobs = db.fetch_unlettered_jobs(limit=constants.MAX_JOBS_PER_BATCH_RUN)
    for job in jobs:
        remaining = rate_limit.remaining_daily_budget()
        if remaining < constants.ESTIMATED_CALLS_PER_JOB:
            logger.warning(
                "daily budget low (remaining=%s, need~%s), stopping batch early",
                remaining, constants.ESTIMATED_CALLS_PER_JOB,
            )
            break
        letter = db.ensure_letter_row(job["id"])
        db.update_letter(letter["id"], {"status": constants.STATUS_PROCESSING})
        _run_job(job["id"])


@app.post("/runs/batch")
def run_batch(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_batch_background)
    return {"started": True}


@app.get("/jobs")
def get_jobs(
    keyword: Optional[str] = None,
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    flags: Optional[List[str]] = Query(default=None),
):
    """All scraped jobs, joined with letter status + flagged state. `status`
    filters on the letter's status; pass "none" for jobs with no letter yet.
    `flags` keeps only jobs matching at least one of: "custom" (custom apply
    instructions), "old" (30+ days since posting's own last update), "none"
    (no flag at all). Omit for no flag filtering."""
    return db.list_jobs(keyword=keyword, job_type=job_type, status=status, flags=flags)


@app.get("/jobs/filters")
def get_job_filters():
    return db.list_job_filter_options()


@app.post("/jobs/{job_id}/draft")
def draft_job(job_id: int, background_tasks: BackgroundTasks):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    existing = db.get_letter_by_job(job_id)
    if existing and existing["status"] == constants.STATUS_PENDING:
        raise HTTPException(
            400, "this job was flagged for custom apply instructions -- use /letters/{id}/continue"
        )
    if existing and existing["status"] == constants.STATUS_PROCESSING:
        raise HTTPException(409, "already processing")

    remaining = rate_limit.remaining_daily_budget()
    if remaining < constants.ESTIMATED_CALLS_PER_JOB:
        raise HTTPException(429, f"daily LLM call budget nearly exhausted (remaining={remaining})")

    letter = db.ensure_letter_row(job_id)
    db.update_letter(letter["id"], {"status": constants.STATUS_PROCESSING})
    background_tasks.add_task(_run_job, job_id)
    return db.get_letter(letter["id"])


def _run_selected_jobs_background(job_ids):
    for job_id in job_ids:
        existing = db.get_letter_by_job(job_id)
        if existing and existing["status"] in (constants.STATUS_PENDING, constants.STATUS_PROCESSING):
            continue

        remaining = rate_limit.remaining_daily_budget()
        if remaining < constants.ESTIMATED_CALLS_PER_JOB:
            logger.warning("daily budget low, stopping selected-jobs run early")
            break

        letter = db.ensure_letter_row(job_id)
        db.update_letter(letter["id"], {"status": constants.STATUS_PROCESSING})
        _run_job(job_id)


@app.post("/jobs/draft-selected")
def draft_selected_jobs(body: DraftJobsBody, background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_selected_jobs_background, body.job_ids)
    return {"started": True, "job_ids": body.job_ids}


@app.get("/letters")
def get_letters(status: Optional[str] = None):
    return db.list_letters(status=status)


@app.get("/letters/{letter_id}")
def get_letter(letter_id: int):
    letter = db.get_letter(letter_id)
    if not letter:
        raise HTTPException(404, "letter not found")
    return letter


def _continue_background(job_id, letter_id, job_context, feedback):
    try:
        run_continue_from_pending(job_id, letter_id, job_context, feedback)
    except Exception as exc:
        logger.error("letter_id=%s continue failed: %s", letter_id, exc)
        db.update_letter(
            letter_id, {"status": constants.STATUS_REJECTED, "rejection_feedback": f"run failed: {exc}"}
        )


@app.post("/letters/{letter_id}/continue")
def continue_pending_letter(letter_id: int, body: FeedbackBody, background_tasks: BackgroundTasks):
    """For a letter Discovery flagged (status=pending) -- runs Matcher then
    Writer+Critic, with the human's review feedback folded in."""
    letter = db.get_letter(letter_id)
    if not letter:
        raise HTTPException(404, "letter not found")
    if letter["status"] != constants.STATUS_PENDING:
        raise HTTPException(400, f"letter status is {letter['status']}, not pending")

    remaining = rate_limit.remaining_daily_budget()
    if remaining < constants.ESTIMATED_CALLS_PER_JOB:
        raise HTTPException(429, f"daily LLM call budget nearly exhausted (remaining={remaining})")

    db.update_letter(letter_id, {"status": constants.STATUS_PROCESSING})
    background_tasks.add_task(_continue_background, letter["job_id"], letter_id, letter["job_context"], body.feedback)
    return db.get_letter(letter_id)


def _redraft_background(job_id, letter_id, job_context, fit_assessment, feedback):
    try:
        run_manual_redraft(job_id, letter_id, job_context, fit_assessment, feedback)
    except Exception as exc:
        logger.error("letter_id=%s redraft failed: %s", letter_id, exc)
        db.update_letter(
            letter_id, {"status": constants.STATUS_REJECTED, "rejection_feedback": f"run failed: {exc}"}
        )


@app.patch("/letters/{letter_id}")
def update_letter_status(letter_id: int, body: StatusBody, background_tasks: BackgroundTasks):
    """Free status change in any direction (approved <-> drafted <-> rejected).
    Plain DB update for approved/drafted/pending. Rejected also kicks off a
    background Writer+Critic redraft (reusing stored job_context/fit_assessment),
    status shows 'processing' until it lands back on 'drafted'."""
    letter = db.get_letter(letter_id)
    if not letter:
        raise HTTPException(404, "letter not found")
    if letter["status"] == constants.STATUS_PROCESSING:
        raise HTTPException(409, "already processing")

    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(VALID_STATUSES)}")

    if body.status in (constants.STATUS_APPROVED, constants.STATUS_PENDING):
        db.update_letter(letter_id, {"status": body.status})

    elif body.status == constants.STATUS_DRAFTED:
        db.update_letter(letter_id, {"status": constants.STATUS_DRAFTED, "rejection_feedback": None})

    elif body.status == constants.STATUS_REJECTED:
        remaining = rate_limit.remaining_daily_budget()
        if remaining < constants.ESTIMATED_CALLS_PER_JOB:
            raise HTTPException(
                429,
                f"daily LLM call budget nearly exhausted (remaining={remaining}), "
                "try again after it resets",
            )

        db.update_letter(
            letter_id,
            {
                "status": constants.STATUS_PROCESSING,
                "rejection_feedback": body.feedback,
                "revision_count": (letter.get("revision_count") or 0) + 1,
            },
        )
        background_tasks.add_task(
            _redraft_background, letter["job_id"], letter_id, letter["job_context"], letter["fit_assessment"], body.feedback
        )

    return db.get_letter(letter_id)


@app.get("/usage")
def get_usage():
    client = db.get_client()
    llm_calls = client.table("llm_calls").select("*").execute().data
    tool_calls = client.table("tool_calls").select("*").execute().data

    total_cost = sum(r.get("estimated_cost_usd") or 0 for r in llm_calls)
    total_tokens = sum(r.get("total_tokens") or 0 for r in llm_calls)

    by_node = {}
    for r in llm_calls:
        node = r.get("node_name") or "unknown"
        bucket = by_node.setdefault(node, {"calls": 0, "tokens": 0, "cost": 0.0})
        bucket["calls"] += 1
        bucket["tokens"] += r.get("total_tokens") or 0
        bucket["cost"] += r.get("estimated_cost_usd") or 0

    return {
        "llm_calls": len(llm_calls),
        "tool_calls": len(tool_calls),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "by_node": by_node,
    }


@app.get("/llm_calls")
def get_llm_calls(limit: int = 200):
    return db.list_llm_calls(limit=limit)
