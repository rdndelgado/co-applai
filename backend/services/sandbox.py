import docker
from docker.errors import ContainerError, NotFound

from utils.logger import get_logger

logger = get_logger(__name__)

SANDBOX_IMAGE = "python:3.12-slim"
DEFAULT_TIMEOUT_SECONDS = 10
MEMORY_LIMIT = "128m"


def run_sandboxed(code):
    """Runs `code` as a Python script in a locked-down, ephemeral container:
    no network, memory-capped, killed and removed after `DEFAULT_TIMEOUT_SECONDS`
    regardless of outcome. Returns {stdout, stderr, exit_code}.
    """
    client = docker.from_env()
    container = None
    try:
        container = client.containers.run(
            SANDBOX_IMAGE,
            ["python3", "-c", code],
            network_disabled=True,
            mem_limit=MEMORY_LIMIT,
            detach=True,
        )
        try:
            result = container.wait(timeout=DEFAULT_TIMEOUT_SECONDS)
            exit_code = result.get("StatusCode", 1)
        except Exception:
            container.kill()
            return {"stdout": "", "stderr": "sandbox timed out", "exit_code": -1}

        stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
        return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}

    except ContainerError as exc:
        logger.error("sandbox container error: %s", exc)
        return {"stdout": "", "stderr": str(exc), "exit_code": -1}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except NotFound:
                pass
