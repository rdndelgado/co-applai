from typing import Optional, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from agents.critic import run_critic
from agents.discovery import run_discovery
from agents.matcher import run_matcher
from agents.writer import run_writer
from core import constants
from helpers.apply_format import format_special_instructions
from helpers.profile import load_profile
from services import db
from utils.logger import get_logger

logger = get_logger(__name__)


class LetterState(TypedDict, total=False):
    job_id: int
    letter_id: int
    job_context: dict
    fit_assessment: dict
    draft: str
    auto_revision_count: int
    feedback: Optional[str]


def discovery_node(state):
    job_id = state["job_id"]
    job_context = run_discovery(job_id, job_id)

    fields = {"job_context": job_context}
    special = job_context.get("special_apply_instructions")
    if special:
        # flagged -- pause here, awaiting human review/feedback before
        # Matcher/Writer/Critic run (see route_after_discovery). content
        # holds the rules themselves, not a draft, so there's something
        # concrete to read and respond to with feedback.
        fields["status"] = constants.STATUS_PENDING
        fields["content"] = format_special_instructions(special)

    db.update_letter(state["letter_id"], fields)
    return {"job_context": job_context}


def route_after_discovery(state):
    return END if state["job_context"].get("special_apply_instructions") else "matcher"


def matcher_node(state):
    job_id = state["job_id"]
    fit_assessment = run_matcher(job_id, job_id, state["job_context"])
    db.update_letter(state["letter_id"], {"fit_assessment": fit_assessment})
    return {"fit_assessment": fit_assessment}


def writer_node(state):
    job_id = state["job_id"]
    profile = load_profile()
    run_writer(
        job_id,
        job_id,
        state["letter_id"],
        state["job_context"],
        state["fit_assessment"],
        profile,
        feedback=state.get("feedback"),
    )
    letter = db.get_letter(state["letter_id"])
    return {"draft": letter["content"], "feedback": None}


def critic_node(state):
    job_id = state["job_id"]
    result = run_critic(job_id, job_id, state["draft"], state["job_context"])

    if result["verdict"] == "pass":
        return {"feedback": None}

    auto_count = state.get("auto_revision_count", 0) + 1
    if auto_count >= constants.MAX_AUTO_REVISIONS:
        logger.warning(
            "job_id=%s hit MAX_AUTO_REVISIONS, leaving draft as-is for review",
            job_id,
        )
        return {"feedback": None, "auto_revision_count": auto_count}

    return {"feedback": result["feedback"], "auto_revision_count": auto_count}


def route_after_critic(state):
    return "writer" if state.get("feedback") else END


def build_graph(checkpointer):
    """Discovery -> Matcher -> Writer -> Critic, looping Writer<->Critic
    (capped at MAX_AUTO_REVISIONS) until Critic passes, then ends. No
    interrupt() -- the pipeline always runs start to finish in one call.
    Approve/reject/redraft are plain status changes handled outside the
    graph (see run_manual_redraft below and app.py), not a paused thread
    resume -- a completed thread has nothing left to resume, which doesn't
    fit "change status freely after the fact" (approved -> drafted ->
    rejected, in any order).
    """
    graph = StateGraph(LetterState)
    graph.add_node("discovery", discovery_node)
    graph.add_node("matcher", matcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("critic", critic_node)

    graph.add_edge(START, "discovery")
    graph.add_conditional_edges("discovery", route_after_discovery, {"matcher": "matcher", END: END})
    graph.add_edge("matcher", "writer")
    graph.add_edge("writer", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"writer": "writer", END: END})

    return graph.compile(checkpointer=checkpointer)


def run_manual_redraft(job_id, letter_id, job_context, fit_assessment, feedback):
    """Writer+Critic loop outside the graph, for a letter that already has
    job_context/fit_assessment from a prior full run. Used whenever a letter
    is set to 'rejected' (from any prior status) -- reuses Discovery/Matcher's
    stored output instead of re-running them."""
    profile = load_profile()
    current_feedback = feedback
    auto_count = 0

    while True:
        run_writer(job_id, job_id, letter_id, job_context, fit_assessment, profile, feedback=current_feedback)
        draft = db.get_letter(letter_id)["content"]
        result = run_critic(job_id, job_id, draft, job_context)

        if result["verdict"] == "pass":
            break

        auto_count += 1
        if auto_count >= constants.MAX_AUTO_REVISIONS:
            logger.warning(
                "job_id=%s hit MAX_AUTO_REVISIONS during manual redraft, leaving draft as-is",
                job_id,
            )
            break

        current_feedback = result["feedback"]

    db.update_letter(letter_id, {"status": constants.STATUS_DRAFTED})


def run_continue_from_pending(job_id, letter_id, job_context, feedback):
    """For a letter Discovery flagged and paused on (status=pending). Runs
    Matcher (never ran yet for this letter) then the Writer+Critic loop,
    with the human's feedback folded in from the start."""
    fit_assessment = run_matcher(job_id, job_id, job_context)
    db.update_letter(letter_id, {"fit_assessment": fit_assessment})
    run_manual_redraft(job_id, letter_id, job_context, fit_assessment, feedback)


_checkpointer_cm = None
_graph = None


def get_graph():
    """Lazily builds the graph with a Postgres checkpointer. Reused across
    requests within one process -- the checkpointer connection stays open.
    Still useful for per-run history/observability even without interrupt()."""
    global _checkpointer_cm, _graph
    if _graph is None:
        _checkpointer_cm = PostgresSaver.from_conn_string(constants.SUPABASE_DB_URL)
        checkpointer = _checkpointer_cm.__enter__()
        checkpointer.setup()
        _graph = build_graph(checkpointer)
    return _graph
