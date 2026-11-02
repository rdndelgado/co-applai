import json

from agents.runner import run_agent_json
from core import constants
from helpers.apply_format import is_short_format, obfuscate_link
from helpers.profile import load_profile
from tools.job_tools import make_get_profile_tool

BASE_RULES = """You are the Critic Agent in a job-application pipeline,
reviewing a message for onlinejobs.ph's "Apply" box -- not a cover letter.
Call get_profile to verify no claims are fabricated. Always check:
- No employer/company names anywhere -- candidate's past employers or this
  job's company. Concepts and value only.
- Sounds straightforward and genuine -- plain, direct language, not sales
  copy or generic enthusiasm phrases.
- Factual accuracy -- every claim must be traceable to the profile.
- Opens with a short, casual, genuine-interest greeting (e.g. "Hey, this
  caught my eye -- ..."), not a formal "Dear Hiring Team." Revise if it
  jumps straight into substance with no greeting, or if the greeting reads
  stiff/formal instead of casual.
- No formal sign-off ("Best regards" / "Sincerely") at the end -- it should
  read as a direct message, not a letter.
- No statement or implication of currently holding a full-time job elsewhere.
- No em dash (—) or en dash (–) anywhere -- reads as AI-generated.
- Includes the portfolio link in its exact obfuscated form (given below) --
  not the real URL with literal dots, not reformatted, not dropped: {portfolio}
"""


def _build_prompt(job_context, portfolio):
    special = job_context.get("special_apply_instructions") or {}
    questions = special.get("questions") or []
    must_start_with = special.get("must_start_with")
    requires_attachment = special.get("requires_attachment")

    rules = BASE_RULES.format(portfolio=portfolio)

    if must_start_with:
        rules += f'\n- Message begins with the exact word "{must_start_with}".'

    if questions:
        rules += (
            "\n- Every one of these questions is answered, concisely but "
            "specifically, not vague or generic:\n"
        )
        for q in questions:
            rules += f"  - {q}\n"
    else:
        rules += (
            f"\n- Hard length limit: 2-3 short sentences, around "
            f"{constants.MAX_MESSAGE_CHARS} characters. Reject anything "
            "meaningfully longer."
            "\n- After the greeting, the core idea must be a confident "
            "capability statement (\"I've done this before, I can help "
            "you\"), not an immediate deep dive into details -- the "
            "recruiter hasn't asked for specifics yet. Revise if it reads "
            "like a case study or lists multiple projects/details instead "
            "of one credible, value-focused detail backing up the claim."
        )

    if requires_attachment:
        rules += "\n- Message mentions sharing the requested attachment."

    rules += """
Respond with ONLY a JSON object (no markdown fences, no commentary) with this
exact shape:
{
  "verdict": "pass" or "revise",
  "feedback": "specific, actionable feedback if revise; empty string if pass"
}"""
    return rules


def run_critic(job_id, thread_id, draft, job_context):
    profile = load_profile()
    portfolio_url = profile.get("links", {}).get("portfolio", "")
    expected_link = obfuscate_link(portfolio_url) if portfolio_url else ""

    # deterministic gates, no LLM call needed for objective checks
    if any(dash in draft for dash in ("—", "–")):
        return {
            "verdict": "revise",
            "feedback": "Contains an em dash (—) or en dash (–) -- remove it, use a period or comma instead.",
        }

    if expected_link and expected_link not in draft:
        return {
            "verdict": "revise",
            "feedback": f"Missing the portfolio link. Include it exactly as: {expected_link}",
        }

    bare_domain = portfolio_url.split("//")[-1].rstrip("/") if portfolio_url else ""
    if bare_domain and bare_domain in draft:
        return {
            "verdict": "revise",
            "feedback": (
                f"Contains the raw link with literal dots -- use the obfuscated "
                f"form instead: {expected_link}"
            ),
        }

    if is_short_format(job_context) and len(draft) > constants.MAX_MESSAGE_CHARS_HARD_LIMIT:
        return {
            "verdict": "revise",
            "feedback": (
                f"Too long: {len(draft)} characters, target is "
                f"{constants.MAX_MESSAGE_CHARS}. Cut it down to 2-3 short sentences."
            ),
        }

    tools = [make_get_profile_tool(job_id, thread_id)]
    user_content = f"draft:\n{draft}\n\njob_context:\n{json.dumps(job_context)}"
    prompt = _build_prompt(job_context, expected_link)
    return run_agent_json("critic", prompt, tools, user_content, job_id, thread_id)
