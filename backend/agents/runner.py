from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_deepseek import ChatDeepSeek

from core import constants
from helpers.json_parse import parse_json_response
from services import rate_limit, usage
from utils.logger import get_logger

logger = get_logger(__name__)


def _build_llm(model, tools):
    extra_kwargs = constants.DISABLE_THINKING_KWARGS if model == constants.DEEPSEEK_MODEL else {}
    llm = ChatDeepSeek(
        model=model,
        api_key=constants.DEEPSEEK_API_KEY,
        timeout=constants.DEEPSEEK_TIMEOUT_SECONDS,
        **extra_kwargs,
    )
    return llm.bind_tools(tools) if tools else llm


def _invoke_with_fallback(primary_llm, fallback_llm, messages):
    """Tries the primary model first (capped at DEEPSEEK_TIMEOUT_SECONDS by
    the client itself). On any failure -- timeout, overload, deprecation --
    falls back to DEEPSEEK_FALLBACK_MODEL once. Raises if both fail."""
    rate_limit.wait_for_rpm_slot()
    try:
        return primary_llm.invoke(messages), constants.DEEPSEEK_MODEL
    except Exception as exc:
        logger.warning(
            "model=%s failed (%s), falling back to model=%s",
            constants.DEEPSEEK_MODEL, exc, constants.DEEPSEEK_FALLBACK_MODEL,
        )
        rate_limit.wait_for_rpm_slot()
        return fallback_llm.invoke(messages), constants.DEEPSEEK_FALLBACK_MODEL


def run_agent(node_name, system_prompt, tools, user_content, job_id, thread_id):
    """Manual tool-calling loop: invoke the model, execute any requested tool
    calls, feed results back, repeat until it returns plain content or the
    round cap is hit. Every model call is logged to llm_calls regardless of
    whether it ended in a tool call or a final answer.
    """
    primary_llm = _build_llm(constants.DEEPSEEK_MODEL, tools)
    fallback_llm = _build_llm(constants.DEEPSEEK_FALLBACK_MODEL, tools)
    tool_map = {t.name: t for t in tools}

    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_content)]

    for round_num in range(constants.MAX_AGENT_TOOL_ROUNDS):
        with usage.timer() as t:
            try:
                response, model_used = _invoke_with_fallback(primary_llm, fallback_llm, messages)
            except Exception as exc:
                usage.log_llm_call(
                    thread_id, job_id, node_name, constants.DEEPSEEK_MODEL,
                    None, None, None, t["duration_ms"],
                    status="error", error_message=str(exc),
                )
                raise

        meta = getattr(response, "usage_metadata", None) or {}
        cached = (meta.get("input_token_details") or {}).get("cache_read", 0)
        usage.log_llm_call(
            thread_id,
            job_id,
            node_name,
            model_used,
            meta.get("input_tokens"),
            meta.get("output_tokens"),
            cached,
            t["duration_ms"],
        )

        messages.append(response)

        if not getattr(response, "tool_calls", None):
            return response.content

        for call in response.tool_calls:
            tool_fn = tool_map.get(call["name"])
            if tool_fn is None:
                result = {"error": f"unknown tool {call['name']}"}
            else:
                try:
                    result = tool_fn.invoke(call["args"])
                except Exception as exc:
                    result = {"error": str(exc)}
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    raise RuntimeError(f"{node_name} exceeded MAX_AGENT_TOOL_ROUNDS without a final answer")


def run_agent_json(node_name, system_prompt, tools, user_content, job_id, thread_id, max_retries=2):
    """run_agent, but for agents whose final answer must be JSON. Retries
    with the parse error fed back to the model if it returns something that
    doesn't parse -- DeepSeek occasionally emits a stray unescaped character
    that breaks strict JSON parsing."""
    content = user_content
    last_error = None

    for attempt in range(max_retries + 1):
        raw = run_agent(node_name, system_prompt, tools, content, job_id, thread_id)
        try:
            return parse_json_response(raw)
        except Exception as exc:
            last_error = exc
            logger.warning("%s returned invalid JSON (attempt %s): %s", node_name, attempt + 1, exc)
            content = (
                f"{user_content}\n\nYour previous response was not valid JSON "
                f"(error: {exc}). Raw response was:\n{raw}\n\n"
                "Return ONLY the corrected valid JSON object, nothing else."
            )

    raise ValueError(f"{node_name} failed to return valid JSON after {max_retries + 1} attempts: {last_error}")
