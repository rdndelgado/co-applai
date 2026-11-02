import resource
import subprocess
import sys
import tempfile

DEFAULT_TIMEOUT_SECONDS = 10
MEMORY_LIMIT_BYTES = 128 * 1024 * 1024


def _limit_resources():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (DEFAULT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


def run_sandboxed(code):
    """Runs `code` as a Python script in a subprocess, not a container --
    there's no Docker socket available on this deployment target. This is a
    deliberate MVP tradeoff, not the real isolation story; a dedicated
    sandbox service is the right answer once this needs to be production
    hardened. What containment we can get without Docker:

    - a blank environment (no inherited API keys/DB credentials)
    - run from an empty temp directory, not the app's own working directory
    - memory and CPU limits, no forking (RLIMIT_NPROC=0)
    - killed after DEFAULT_TIMEOUT_SECONDS regardless of outcome

    What it does NOT give us: network isolation, or protection against a
    process that reads/writes files under its temp cwd. Acceptable here
    because the Matcher only ever writes small, purely computational scoring
    scripts against JSON it's already been handed.

    Returns {stdout, stderr, exit_code}.
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                cwd=tmpdir,
                env={},
                preexec_fn=_limit_resources,
            )
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "sandbox timed out", "exit_code": -1}
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "exit_code": -1}
