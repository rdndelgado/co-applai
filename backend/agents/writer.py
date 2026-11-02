import json

from agents.runner import run_agent
from core import constants
from helpers.apply_format import obfuscate_link
from tools.job_tools import make_save_draft_tool

BASE_RULES = """You are the Writer Agent in a job-application pipeline. You
write the message the candidate pastes into onlinejobs.ph's "Apply" box --
this is NOT a cover letter.

Always true, no exceptions:
- Speak only in concepts and value delivered -- NEVER name any
  employer/company, not the candidate's own past employers and not this
  job's company.
- Sound straightforward and genuine -- plain, direct language, not sales
  copy, not generic enthusiasm ("I'm excited to..." / "I believe I'd be a
  great fit...").
- Ground every claim ONLY in job_context.applicable_experience and
  applicable_tech_stack -- never invent details.
- Open with a short, casual greeting that shows genuine interest in the
  role (e.g. "Hey, this caught my eye -- ..." / "Hi, really interested in
  this one, ..."). Not a formal "Dear Hiring Team." Keep it brief, then move
  straight into the hook.
- No formal sign-off ("Best regards" / "Sincerely") at the end -- this is a
  direct message, not a letter.
- Never state or imply currently holding a full-time job elsewhere.
- Never use an em dash (—) or en dash (–) anywhere -- it reads as AI-generated.
  Use a period, comma, or "and" instead.
- Always include the portfolio link, written EXACTLY as given below, verbatim
  -- do not reformat it, do not add "https://" or "www", do not turn it back
  into a normal-looking URL (this exact format avoids automatic link-flagging
  on the job board): {portfolio}
- Tone: {tone}.
"""


def _build_prompt(job_context, tone, availability, portfolio):
    special = job_context.get("special_apply_instructions") or {}
    questions = special.get("questions") or []
    must_start_with = special.get("must_start_with")
    requires_attachment = special.get("requires_attachment")
    attachment_note = special.get("attachment_note")

    rules = BASE_RULES.format(tone=tone, portfolio=portfolio)

    if must_start_with:
        rules += f'\n- The message MUST begin with the exact word "{must_start_with}".'

    if questions:
        rules += (
            "\n- Answer every one of these questions, concisely but "
            "specifically, drawing on job_context.applicable_experience and "
            "applicable_tech_stack for real grounded detail. Roughly 1-3 "
            "sentences per question, no padding:\n"
        )
        for q in questions:
            rules += f"  - {q}\n"
        rules += "- No overall length cap given the questions, but don't pad beyond what answers them."
    else:
        rules += (
            f"\n- 2-3 short sentences, target {constants.MAX_MESSAGE_CHARS} "
            "characters total. This is a hard limit, not a suggestion -- the "
            "greeting counts toward it, so keep the greeting to a few words."
            "\n- Structure, in order: (1) the greeting, (2) a confident "
            "capability statement -- the core idea is \"I've done this "
            "before, I can help you\" -- NOT a deep dive into details yet, "
            "since the recruiter hasn't asked for specifics, (3) ONE "
            "concrete detail backing that up (tech stack + experience from "
            "job_context.applicable_experience/applicable_tech_stack) framed "
            "around the value it delivers for this kind of work, tied to "
            "this job's key_requirements. Enough to be credible, not an "
            "exhaustive case study -- save the deep dive for if they ask."
        )

    if requires_attachment:
        rules += (
            f"\n- Mention that you'll share the requested attachment "
            f"({attachment_note or 'a Loom or code link'})."
        )

    if availability:
        rules += (
            f"\n- Availability, if timezone/schedule overlap is relevant to "
            f"this job (otherwise omit entirely, don't force it in): "
            f"{availability}"
        )

    rules += (
        "\n\nYou are given job_context and fit_assessment (JSON), and "
        "possibly feedback from a previous rejected draft -- apply that "
        "feedback directly. When done, call save_draft with the final "
        "message text. After calling save_draft, respond with a short "
        "confirmation sentence."
    )
    return rules


def run_writer(job_id, thread_id, letter_id, job_context, fit_assessment, profile, feedback=None):
    tools = [make_save_draft_tool(job_id, thread_id, letter_id)]
    tone = profile.get("tone", "professional")
    availability = profile.get("availability", "")
    portfolio_url = profile.get("links", {}).get("portfolio", "")
    portfolio = obfuscate_link(portfolio_url) if portfolio_url else ""
    system_prompt = _build_prompt(job_context, tone, availability, portfolio)

    user_content = (
        f"job_context:\n{json.dumps(job_context)}\n\n"
        f"fit_assessment:\n{json.dumps(fit_assessment)}"
    )
    if feedback:
        user_content += (
            f"\n\nThe previous draft was rejected with this feedback, "
            f"revise accordingly:\n{feedback}"
        )

    return run_agent("writer", system_prompt, tools, user_content, job_id, thread_id)
