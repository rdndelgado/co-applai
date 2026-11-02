from agents.runner import run_agent_json
from tools.job_tools import make_get_job_details_tool, make_get_profile_tool

SYSTEM_PROMPT = """You are the Discovery Agent in a job-application pipeline.
Call get_job_details to read the job posting, and get_profile to read the
candidate's background. Cross-reference them, then respond with ONLY a JSON
object (no markdown fences, no commentary) with this exact shape:
{
  "role_summary": "...",
  "key_requirements": ["..."],
  "must_have_skills": ["..."],
  "nice_to_have_skills": ["..."],
  "job_type": "...",
  "rate": "...",
  "red_flags": ["..."],
  "applicable_experience": "...",
  "applicable_tech_stack": ["..."],
  "special_apply_instructions": null
}

Rules for each field:
- "red_flags": vague scope, unrealistic pay, etc. Empty list if none.
- "applicable_experience": pick exactly ONE thing from the candidate's
  background that's most relevant to this job. Describe it as a concept and
  the value it delivered (e.g. "built an end-to-end workflow automating
  candidate screening and multi-channel notifications") -- NEVER name the
  employer/company it happened at. This gets used directly in a short apply
  message, so it must stand on its own without company context.
- "applicable_tech_stack": only the candidate's skills that actually overlap
  with this job's requirements -- not their whole skill list.
- "special_apply_instructions": most job posts have none -- leave this null.
  Some posts include explicit custom instructions for how to apply: a
  required opening word for the message, specific questions the applicant
  must answer, or a requested attachment (Loom video, code link, etc). If the
  job description contains anything like that, extract it as:
  {
    "must_start_with": "..." or null,
    "questions": ["..."],
    "requires_attachment": true/false,
    "attachment_note": "...",
    "raw_instructions": "the original instructions text, verbatim"
  }
  Otherwise this field is null. Do not infer instructions that aren't
  explicitly stated -- only extract what's literally written."""


def run_discovery(job_id, thread_id):
    tools = [
        make_get_job_details_tool(job_id, thread_id),
        make_get_profile_tool(job_id, thread_id),
    ]
    return run_agent_json(
        "discovery",
        SYSTEM_PROMPT,
        tools,
        "Discover and summarize this job, and what from the candidate's background applies to it.",
        job_id,
        thread_id,
    )
