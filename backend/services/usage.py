import time
from contextlib import contextmanager

from core import constants
from services import db
from utils.logger import get_logger

logger = get_logger(__name__)


@contextmanager
def timer():
    start = time.monotonic()
    box = {"duration_ms": 0}
    try:
        yield box
    finally:
        box["duration_ms"] = int((time.monotonic() - start) * 1000)


def _estimate_cost(model, input_tokens, output_tokens, cached_tokens):
    pricing = constants.MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0, "cached": 0.0})
    cost = (
        (input_tokens or 0) * pricing["input"]
        + (output_tokens or 0) * pricing["output"]
        + (cached_tokens or 0) * pricing["cached"]
    ) / 1_000_000
    return round(cost, 6)


def log_llm_call(
    thread_id,
    job_id,
    node_name,
    model,
    input_tokens,
    output_tokens,
    cached_tokens,
    duration_ms,
    status="success",
    error_message=None,
):
    total_tokens = (input_tokens or 0) + (output_tokens or 0)
    row = {
        "thread_id": str(thread_id),
        "job_id": job_id,
        "node_name": node_name,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": _estimate_cost(model, input_tokens, output_tokens, cached_tokens),
        "duration_ms": duration_ms,
        "status": status,
        "error_message": error_message,
    }
    try:
        db.insert_llm_call(row)
    except Exception as exc:
        logger.error("failed to log llm_call: %s", exc)


def log_tool_call(
    thread_id,
    job_id,
    tool_name,
    input_summary,
    duration_ms,
    status="success",
    error_message=None,
):
    row = {
        "thread_id": str(thread_id),
        "job_id": job_id,
        "tool_name": tool_name,
        "input_summary": input_summary,
        "duration_ms": duration_ms,
        "status": status,
        "error_message": error_message,
    }
    try:
        db.insert_tool_call(row)
    except Exception as exc:
        logger.error("failed to log tool_call: %s", exc)
