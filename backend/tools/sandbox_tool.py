from langchain_core.tools import tool

from services import usage
from services.sandbox import run_sandboxed


def make_run_sandboxed_code_tool(job_id, thread_id):
    @tool
    def run_sandboxed_code(code: str) -> dict:
        """Executes Python code in an isolated, network-disabled sandbox
        container and returns {stdout, stderr, exit_code}. Use this to compute
        things like a fit score between the candidate profile and the job by
        writing your own scoring logic, rather than guessing a number."""
        with usage.timer() as t:
            result = run_sandboxed(code)
        status = "success" if result["exit_code"] == 0 else "error"
        usage.log_tool_call(
            thread_id,
            job_id,
            "run_sandboxed_code",
            code[:200],
            t["duration_ms"],
            status=status,
            error_message=result["stderr"] if status == "error" else None,
        )
        return result

    return run_sandboxed_code
