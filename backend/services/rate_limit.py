import time
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock

from core import constants
from services import db
from utils.logger import get_logger

logger = get_logger(__name__)

_lock = Lock()
_call_times = deque()


def wait_for_rpm_slot():
    """Blocks (sleeps) until issuing another call stays within
    LLM_RPM_LIMIT calls per rolling 60s window. In-memory, per-process --
    fine for this single-process local app, not durable across restarts."""
    while True:
        with _lock:
            now = time.monotonic()
            while _call_times and now - _call_times[0] > 60:
                _call_times.popleft()

            if len(_call_times) < constants.LLM_RPM_LIMIT:
                _call_times.append(now)
                return

            sleep_for = 60 - (now - _call_times[0]) + 0.1

        logger.info("RPM limit reached, sleeping %.1fs", sleep_for)
        time.sleep(sleep_for)


def remaining_daily_budget():
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    used = db.count_llm_calls_since(since)
    return constants.LLM_RPD_LIMIT - used
