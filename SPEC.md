# co-applai — Spec

## Purpose

Generates the short apply-message you paste into onlinejobs.ph's "Apply" box for each job already collected by `onlinejobsph-scraper` (Supabase `jobs` table), based on your own experience profile. This is not a cover letter — onlinejobs.ph only shows the recruiter a preview of the opening before they expand it, so the message is short and front-loads a specific hook. A multi-agent pipeline drafts it, you review and can freely change its status (drafted/approved/rejected, any direction, feedback-driven redraft on rejection). Built as a practice project for agent-harness engineering: LangGraph orchestration, tool calling, and a sandboxed code-execution tool. (DB table/column names still say "letter" throughout — internal naming only, not worth a schema rename for a terminology shift.)

## Stack

- **Backend**: FastAPI + LangGraph (Python)
- **Frontend**: React (Vite)
- **LLM**: DeepSeek, `deepseek-chat` (fallback: `deepseek-reasoner`)
- **Datastore**: same Supabase/Postgres project as `onlinejobsph-scraper` — new `letters` table, plus LangGraph's own checkpoint tables (for pause/resume)
- **Sandbox**: Docker-socket sibling containers — backend mounts the host Docker socket, spins up a locked-down ephemeral container per code-execution tool call, tears it down after. Ties deployment to local/VPS for now (see Risks).
- Deploy target: local / VPS (not yet a managed platform — see sandbox note above)

## Why a monolith (FastAPI + React, not Streamlit)

Chosen over reusing the Streamlit pattern from `onlinejobsph-scraper-view` because the review step here needs real actions with side effects (approve/reject resuming a paused LangGraph run), not just data display — a thin API + frontend separation fits that better and is the point of the practice project (harness engineering, not another dashboard).

## Data model

### Profile (local file, not in Supabase)

`backend/profile.yaml` (gitignored — personal data; `profile.example.yaml` committed as the template). Loaded fresh on every agent run, no caching across edits. Parsed from your resume (`Rudini's Resume.pdf`, generic version) — real bullet-point descriptions per role, not just titles/dates, so the agent has actual accomplishments to draw on.

```yaml
name: ...
headline: ...
location: ...
email: ...
links: {portfolio, linkedin, github}
education:
  - {degree, school, location}
skills:
  tools: [...]
  devops: [...]
experience:
  - role: ...
    company: ...
    location: ...
    duration: ...
    highlights:
      - ...   # real resume bullets, with numbers where you have them
projects:
  - title: ...
    company: ...   # employer / capstone / personal
    description: ...
tone: professional   # professional | casual | direct
```

### Supabase: `letters` table (new)

```sql
create table if not exists letters (
  id bigint generated always as identity primary key,
  job_id bigint not null references jobs(id),
  job_context jsonb,          -- Discovery Agent output, computed once, reused across redrafts
  fit_assessment jsonb,       -- Matcher Agent output, computed once, reused across redrafts
  content text,
  status text not null default 'drafted',  -- drafted | approved | rejected
  rejection_feedback text,          -- from human reject
  revision_count int not null default 0,       -- human reject → redraft cycles
  auto_revision_count int not null default 0,  -- Critic reject → redraft cycles (capped at MAX_AUTO_REVISIONS = 3)
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists letters_status_idx on letters (status);
create unique index if not exists letters_job_id_idx on letters (job_id);
```

One letter per job (`job_id` unique) — a rejection doesn't create a new row, it updates the existing one and feeds `rejection_feedback` back into a redraft.

### Supabase: `llm_calls` and `tool_calls` tables (new — usage/cost observability)

Split in two because they track different things: `llm_calls` is specifically model token usage (cost), `tool_calls` is every tool invocation regardless of whether it burned tokens (e.g. a Supabase read or a sandboxed exec). Both link back to the same `thread_id`/`job_id` so a full run is traceable end to end — this pairing is itself part of the harness-engineering practice (you can't tune what you can't see).

```sql
create table if not exists llm_calls (
  id bigint generated always as identity primary key,
  thread_id text not null,          -- langgraph thread (= job_id for this graph)
  job_id bigint references jobs(id),
  node_name text,                   -- discovery | matcher | writer | critic
  model text not null,              -- e.g. "deepseek-chat"
  input_tokens int,
  output_tokens int,
  cached_tokens int,                -- tokens served from the model's cache (cheaper/free, depending on provider)
  total_tokens int,
  estimated_cost_usd numeric(10,6), -- computed at insert time from a per-model price table in code
  duration_ms int,
  status text not null default 'success',  -- success | error
  error_message text,
  created_at timestamptz not null default now()
);

create table if not exists tool_calls (
  id bigint generated always as identity primary key,
  thread_id text not null,
  job_id bigint references jobs(id),
  tool_name text not null,          -- get_job_details | get_profile | run_sandboxed_code | save_draft
  input_summary text,               -- short, not the full payload — avoid duplicating large content
  status text not null default 'success',  -- success | error
  error_message text,
  duration_ms int,
  created_at timestamptz not null default now()
);

create index if not exists llm_calls_thread_idx on llm_calls (thread_id);
create index if not exists tool_calls_thread_idx on tool_calls (thread_id);
```

`estimated_cost_usd` is computed at the moment each call is logged, from a per-model price table living in `core/constants.py` (`$/1M tokens` for input/output/cached, source: provider's published pricing) — not recomputed later from raw tokens, so a row's cost stays accurate to whatever pricing was actually in effect when the call happened, even if prices change afterward. On Gemini's free tier this will mostly compute to `0`, which is fine — the token/duration columns are still useful on their own, and the cost column is already correct the moment you switch to a paid tier or a different model.

Both get a row written by a thin wrapper around the LLM client and the tool-calling layer respectively, not scattered manual inserts per call site — one wrapper each, so every call is logged the same way regardless of which node/tool triggered it.

### LangGraph checkpointer

Postgres checkpointer (`langgraph-checkpoint-postgres`) pointed at the same Supabase connection string. LangGraph manages its own checkpoint tables via its `setup()` call — not hand-defined here. `thread_id` = the `letters.job_id` (or `letters.id` once the row exists), so each job's draft/review/redraft cycle is its own resumable thread.

## Agents (LangGraph)

Four distinct agent roles, each with its own system prompt and its own narrow tool access — not one agent doing everything. Discovery/Matcher outputs are computed once per job and persisted (`letters.job_context`, `letters.fit_assessment`), so a redraft (human- or critic-triggered) re-runs only Writer (+ Critic), not the whole pipeline.

```
fetch_unlettered_jobs
        │
        ▼ (per job, as a batch of threads)
  Discovery Agent ──► job_context (role summary, requirements, red flags)
        │
        ▼
  Matcher Agent ──► fit_assessment (score, gaps, recommended angle)
        │
        ▼
  Writer Agent ──► draft ──► save_draft(status=drafted) ──┐
        ▲                                                  │
        │                                                  ▼
        │                                         Critic Agent
        │                                                  │
        │                           ┌──────────────────────┴──────────────────────┐
        │                        revise (+ feedback,                           pass
        │                    auto_revision_count += 1,                           │
        │                   capped at MAX_AUTO_REVISIONS=3)                      ▼
        │                           │                              interrupt() — wait for human
        └───────────────────────────┘                                           │
                                                           ┌──────────────────────┴──────────────────────┐
                                                        approved                               rejected (+ feedback)
                                                           │                                              │
                                                           ▼                                              ▼
                                                  save(status=approved)                    save(status=rejected,
                                                        [end]                               rejection_feedback,
                                                                                         revision_count += 1)
                                                                                                    │
                                                                                            back to Writer Agent
```

| agent | input | tools | output |
|---|---|---|---|
| **Discovery** | raw job row | `get_job_details` | `job_context`: role summary, key requirements, must-have vs nice-to-have skills, red flags (vague scope, unrealistic pay) |
| **Matcher** | `job_context` + profile | `get_profile`, `run_sandboxed_code` | `fit_assessment`: match score, matching skills, gaps, recommended angle (which project/experience to foreground) |
| **Writer** | `job_context` + `fit_assessment` + profile + (on redraft) latest feedback | `save_draft` | apply-message draft text, 80-150 words, hook-first opening |
| **Critic** | draft + `job_context` + profile | `get_profile` | `pass`, or `revise` + specific feedback |

Every tool call (and every LLM call) is logged to `tool_calls`/`llm_calls`, tagged with which agent/node made it — see the Data model section above. That per-agent breakdown is the actual point of the harness-engineering practice: seeing which agent burns the most tokens, which one calls tools redundantly, where latency piles up.

`run_sandboxed_code` (Matcher only) is the deliberate code-execution surface: rather than hardcoding a fit-score formula, the agent writes its own scoring logic and executes it via this tool — watching what code it writes and how often it needs to retry is worth tracking on its own.

Critic's `revise` loop is capped at `MAX_AUTO_REVISIONS = 3` (`auto_revision_count`, separate from the human's `revision_count`) so a stuck Critic can't loop forever burning tokens before anything reaches you — after the cap, it passes through to human review regardless, with the Critic's last feedback attached for your visibility.

**Not building a company-research tool.** `jobs.employer_name` is always blank (onlinejobs.ph hides it pre-login — see `onlinejobsph-scraper`'s `docs/mapper-spec.md`), so there's no company name to look up yet. A `search_company_info` tool would have nothing to search for. Revisit only if employer identification gets added upstream.

## Trigger / run flow

Batch, not on-demand per job:

1. `POST /runs/batch` (FastAPI) — queries Supabase for jobs where `jobs.status = 'done'` and no `letters` row exists yet (or `letters.status = 'rejected'`, for redrafts), capped at `MAX_JOBS_PER_BATCH_RUN = 3`.
2. For each, starts (or resumes) a LangGraph thread.
3. Each thread runs until its `interrupt()` node, then pauses — draft is already saved to `letters` with `status = drafted` at that point, so the frontend can show it immediately without waiting on the whole batch.
4. Frontend polls/fetches `GET /letters?status=drafted` and renders each for review.
5. `POST /letters/{id}/approve` or `POST /letters/{id}/reject` (with feedback) resumes that letter's LangGraph thread with the human's decision — LangGraph `Command(resume=...)` against the stored checkpoint.

## API surface (FastAPI)

| method | path | purpose |
|---|---|---|
| POST | `/runs/batch` | kick off batch drafting over unlettered/rejected jobs |
| GET | `/letters` | list letters, filterable by `status` |
| GET | `/letters/{id}` | one letter + its linked job details |
| POST | `/letters/{id}/approve` | resume graph, mark approved |
| POST | `/letters/{id}/reject` | resume graph with feedback, mark rejected, triggers redraft |
| GET | `/usage` | aggregate token/cost and tool-call stats, for a simple observability view in the frontend |

## Project structure

```
co-applai/
  backend/
    core/constants.py       — env config (Supabase, DeepSeek key, Docker socket path, etc.)
    utils/logger.py
    services/
      db.py                 — Supabase I/O (jobs read, letters read/write)
      sandbox.py             — Docker-socket sibling container execution
      graph.py                — LangGraph graph: discovery/matcher/writer/critic nodes, checkpointer wiring
      usage.py                — llm_calls/tool_calls logging wrappers
      rate_limit.py            — global RPM throttle + daily call budget check
    agents/
      discovery.py             — system prompt + node fn, uses get_job_details
      matcher.py                — system prompt + node fn, uses get_profile + run_sandboxed_code
      writer.py                  — system prompt + node fn, uses save_draft
      critic.py                   — system prompt + node fn, uses get_profile
    tools/
      job_tools.py           — get_job_details, get_profile, save_draft
      sandbox_tool.py         — run_sandboxed_code
    helpers/
      profile.py              — profile.yaml loading/parsing
    app.py                    — FastAPI entrypoint, routes
    profile.yaml               — your actual profile (gitignored)
    profile.example.yaml       — template
    requirements.txt
    Dockerfile
  frontend/                   — React app (letters list + review UI + usage view)
  docker-compose.yml           — backend + frontend; backend mounts /var/run/docker.sock
  .env.example
  .gitignore
```

## Setup

1. **DeepSeek API key** — [platform.deepseek.com](https://platform.deepseek.com) → create an API key. Put it in `.env` as `DEEPSEEK_API_KEY`.
2. **Database** — run `backend/schema.sql` once in Supabase's SQL editor (same project as `onlinejobsph-scraper`). Creates `letters`, `llm_calls`, `tool_calls`. LangGraph's own checkpoint tables are created separately, programmatically, via its `setup()` call — not in this file. Also needs the direct Postgres connection string (Supabase dashboard → Settings → Database → Connection pooling → Session mode URI, password URL-encoded) as `SUPABASE_DB_URL` — separate from the `SUPABASE_URL`/`SUPABASE_KEY` REST credentials, needed because `langgraph-checkpoint-postgres` talks Postgres wire protocol directly.
3. **Docker** running locally, socket accessible — required for the sandbox tool.
4. **`backend/profile.yaml`** — already populated from your resume; review before first run.

### Env vars (`backend/.env`)

| var | purpose |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API access |
| `DEEPSEEK_MODEL` / `DEEPSEEK_FALLBACK_MODEL` | default `deepseek-v4-flash` / `deepseek-reasoner` |
| `DEEPSEEK_TIMEOUT_SECONDS` | default `60` — per-call client-side timeout before falling back |
| `LLM_RPM_LIMIT` / `LLM_RPD_LIMIT` | default `60` / `10000` — placeholders, DeepSeek doesn't publish a fixed cap; update once you know your account's real behavior under load |
| `SUPABASE_URL` / `SUPABASE_KEY` | same project as `onlinejobsph-scraper` |
| `SUPABASE_DB_URL` | direct Postgres connection string, for the LangGraph checkpointer |
| `JOBS_TABLE_NAME` | default `jobs` |
| `MAX_JOBS_PER_BATCH_RUN` | default `1` |
| `MAX_AUTO_REVISIONS` | default `3` |

## Open risks / unresolved

- **Docker-socket sandboxing ties deployment to local/VPS.** Giving a container access to its host's Docker daemon is itself a privilege-escalation risk if the sandboxed code ever escapes — acceptable for a local practice project, revisit before any shared/public deployment. `services/sandbox.py` should be the only place that knows this detail, so swapping to a hosted sandbox (e.g. E2B) later is a one-file change.
- **DeepSeek rate/quota behavior under load is unknown** — `LLM_RPM_LIMIT`/`LLM_RPD_LIMIT` are placeholders, not confirmed real limits. `MAX_JOBS_PER_BATCH_RUN = 1` keeps a single run small regardless. A global in-process RPM throttle (`services/rate_limit.py`) and a per-batch daily-budget check (skips remaining jobs in a run once the budget's too low to safely start another) are both in place, plus a client-side timeout + one fallback-model retry per call (`DEEPSEEK_TIMEOUT_SECONDS`, `DEEPSEEK_FALLBACK_MODEL`).
- **`deepseek-v4-flash` is not a confirmed real API model id** — DeepSeek's known convention so far is generic aliases (`deepseek-chat`, `deepseek-reasoner`), not versioned names like this. If it 404s the way `gemini-2.0-flash` did, swap `DEEPSEEK_MODEL`.
- **Thinking-disable param is unverified** — `core.constants.DISABLE_THINKING_KWARGS` (`extra_body={"thinking": {"type": "disabled"}}`) mirrors Anthropic/Google-style toggles by assumption, not confirmed against DeepSeek's v4 API. Only applied to the primary model (fallback `deepseek-chat` isn't a reasoning model). Will need adjusting once tested live.
- **Profile schema above is a starting point**, not finalized — may need more structure (e.g. per-skill proficiency, preferred job types to skip) once real drafts are reviewed.
- **Critic's auto-redraft loop is capped (`auto_revision_count`), human's reject loop is not.** `revision_count` tracks human rejections but nothing stops an endless human reject→redraft cycle on one job; may want a max before surfacing a warning instead of auto-redrafting.
- **Discovery/Matcher outputs aren't invalidated.** `job_context`/`fit_assessment` are computed once and reused on every redraft — fine as long as the underlying job row doesn't change, but there's no check for that; a job updated after its letter was first drafted would draft against stale context.

## Explicitly out of scope (for now)

- On-demand single-job drafting (batch only, per your answer — could add later as a second trigger path without restructuring the graph).
- Resume/profile parsing from a PDF — profile is hand-maintained YAML.
- Any deploy target other than local/VPS (blocked on the sandbox decision above).
