from decouple import config

DEEPSEEK_API_KEY = config("DEEPSEEK_API_KEY", default="")
DEEPSEEK_MODEL = config("DEEPSEEK_MODEL", default="deepseek-v4-flash")
DEEPSEEK_FALLBACK_MODEL = config("DEEPSEEK_FALLBACK_MODEL", default="deepseek-chat")
DEEPSEEK_TIMEOUT_SECONDS = config("DEEPSEEK_TIMEOUT_SECONDS", default=60, cast=int)

# DeepSeek's API doesn't publish a fixed RPM/RPD cap the way Gemini's free
# tier does (pay-as-you-go, server-load-dependent throttling instead) -- these
# are generous placeholders, not a confirmed real limit. Update once you know
# your actual account's behavior under load.
LLM_RPM_LIMIT = config("LLM_RPM_LIMIT", default=60, cast=int)
LLM_RPD_LIMIT = config("LLM_RPD_LIMIT", default=10000, cast=int)

# Conservative per-job call estimate (discovery + matcher + writer + critic,
# including their own tool-call round trips) -- used to decide whether
# there's enough daily budget left to safely start another job.
ESTIMATED_CALLS_PER_JOB = 12

SUPABASE_URL = config("SUPABASE_URL", default="")
SUPABASE_KEY = config("SUPABASE_KEY", default="")
JOBS_TABLE_NAME = config("JOBS_TABLE_NAME", default="jobs")

# Direct Postgres connection string (Supabase dashboard -> Settings -> Database
# -> Connection string, URI format, with the real password filled in). Needed
# by langgraph-checkpoint-postgres, which talks Postgres wire protocol
# directly -- the REST API URL/key above aren't enough for this.
SUPABASE_DB_URL = config("SUPABASE_DB_URL", default="")

MAX_JOBS_PER_BATCH_RUN = config("MAX_JOBS_PER_BATCH_RUN", default=1, cast=int)
MAX_AUTO_REVISIONS = config("MAX_AUTO_REVISIONS", default=3, cast=int)

PROFILE_PATH = "profile.yaml"

STATUS_PENDING = "pending"  # Discovery flagged custom apply instructions, awaiting human review/feedback
STATUS_PROCESSING = "processing"  # a background draft/redraft is running right now
STATUS_DRAFTED = "drafted"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

# $ per 1M tokens. Placeholder zeros -- fill in once you confirm current
# DeepSeek pricing (it changes over time); not asserting a number here that
# might be stale.
MODEL_PRICING = {
    "deepseek-v4-flash": {"input": 0.0, "output": 0.0, "cached": 0.0},
    "deepseek-chat": {"input": 0.0, "output": 0.0, "cached": 0.0},
}

# Disables extended thinking/reasoning output on deepseek-v4-flash. Param
# name/shape is an assumption (mirrors Anthropic/Google-style thinking
# toggles) -- not verified against DeepSeek's actual v4 API yet.
DISABLE_THINKING_KWARGS = {"extra_body": {"thinking": {"type": "disabled"}}}

# Max tool-call round-trips per agent before giving up (safeguard against a
# runaway tool-calling loop within a single agent's turn).
MAX_AGENT_TOOL_ROUNDS = 5

# Target length for the apply-box message, when the job has no custom apply
# instructions overriding it. Bumped up from 150 to make room for the
# mandatory obfuscated portfolio link (~35 chars) that's now required in
# every message -- without this, the link alone would eat most of the old
# budget. HARD_LIMIT has some buffer over the target so the deterministic
# length gate (see agents/critic.py) doesn't flip-flop on borderline cases.
MAX_MESSAGE_CHARS = 190
MAX_MESSAGE_CHARS_HARD_LIMIT = 220

# A job gets flagged "old" in the UI when its own date_updated (the
# posting's last-updated date on the site) is older than this.
OLD_JOB_THRESHOLD_DAYS = 30
