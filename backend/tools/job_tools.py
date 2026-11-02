from langchain_core.tools import tool

from helpers.profile import load_profile
from services import db, usage


def make_get_job_details_tool(job_id, thread_id):
    @tool
    def get_job_details() -> dict:
        """Returns this job's title, description, job_type, rate, and skills."""
        with usage.timer() as t:
            job = db.get_job(job_id)
        usage.log_tool_call(thread_id, job_id, "get_job_details", f"job_id={job_id}", t["duration_ms"])
        return {
            "title": job.get("title"),
            "description": job.get("description"),
            "job_type": job.get("job_type"),
            "rate": job.get("rate"),
            "skills": job.get("skills"),
        }

    return get_job_details


def make_get_profile_tool(job_id, thread_id):
    @tool
    def get_profile() -> dict:
        """Returns the candidate's structured experience profile (skills, work
        history, projects, education, preferred tone)."""
        with usage.timer() as t:
            profile = load_profile()
        usage.log_tool_call(thread_id, job_id, "get_profile", "", t["duration_ms"])
        return profile

    return get_profile


def make_save_draft_tool(job_id, thread_id, letter_id):
    @tool
    def save_draft(content: str) -> str:
        """Saves the drafted application letter for this job."""
        with usage.timer() as t:
            db.update_letter(letter_id, {"content": content, "status": "drafted"})
        usage.log_tool_call(
            thread_id, job_id, "save_draft", f"len={len(content)}", t["duration_ms"]
        )
        return "saved"

    return save_draft
