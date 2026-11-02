import json

from agents.runner import run_agent_json
from tools.job_tools import make_get_profile_tool
from tools.sandbox_tool import make_run_sandboxed_code_tool

SYSTEM_PROMPT = """You are the Matcher Agent in a job-application pipeline.
You are given a structured job_context (JSON), which already names one
applicable experience and tech stack -- Discovery's job, not yours. Your job
is purely quantitative: call get_profile to read the candidate's full
experience, then call run_sandboxed_code to write and execute your own Python
scoring logic comparing the candidate's skills/experience against the job's
requirements -- do not guess a score without running code for it. Respond
with ONLY a JSON object (no markdown fences, no commentary) with this exact
shape:
{
  "match_score": 0-100,
  "matching_skills": ["..."],
  "gaps": ["..."]
}"""


def run_matcher(job_id, thread_id, job_context):
    tools = [
        make_get_profile_tool(job_id, thread_id),
        make_run_sandboxed_code_tool(job_id, thread_id),
    ]
    user_content = f"job_context:\n{json.dumps(job_context)}"
    return run_agent_json("matcher", SYSTEM_PROMPT, tools, user_content, job_id, thread_id)
