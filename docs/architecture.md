# Architecture

## Pipeline this app sits in

co-applai is the last stage of a three-project pipeline that shares one
Supabase project as its datastore:

```
onlinejobsph-mapper   fetches raw job listing HTML from onlinejobs.ph
        |
        v
onlinejobsph-parser   parses that HTML into structured fields, stores rows
        |              in Supabase's `jobs` table (title, description, rate,
        |              job_type, date_updated, skills, employer_name, ...)
        v
     Supabase          shared datastore: `jobs` (mapper/parser) +
                        `letters` / `llm_calls` / `tool_calls` (co-applai)
        |
        v
     co-applai         pulls scraped jobs, drafts an apply-box message
                        against the candidate's profile, flags jobs needing
                        human attention, runs a human-in-the-loop review loop
```

(`onlinejobsph-scraper-view` is a separate read-only Streamlit dashboard over
the same `jobs` table, for scrape observability -- not part of this app's
runtime path.)

## What co-applai does

For each scraped job, co-applai drafts the short message a candidate pastes
into onlinejobs.ph's "Apply" box -- not a cover letter. Two things can divert
a job from the normal path before a draft is written:

- **Old jobs**: a posting whose own `date_updated` is 30+ days stale is
  flagged `is_old` in the UI so it can be filtered out or deprioritized.
- **Custom apply instructions**: some postings require specific steps (e.g.
  "start your message with 'Automation'", "answer these 3 questions", "attach
  a Loom video"). The Discovery agent detects these generically via LLM
  reasoning, not hardcoded keyword matching. A flagged job's letter status is
  set to `pending`, and its `content` is filled with the extracted rules
  (not a draft) so a human has something concrete to read and respond to
  with feedback before any drafting happens.

## Stack

- **Backend**: FastAPI + LangGraph, Python. DeepSeek (`deepseek-v4-flash`,
  falling back to `deepseek-chat`) as the LLM provider.
- **Frontend**: React (Vite).
- **Datastore**: Supabase (Postgres). REST API (`supabase-py`) for CRUD;
  a direct Postgres connection for the LangGraph checkpointer and schema
  migrations.
- **Sandbox**: the Matcher agent's `run_sandboxed_code` tool spins up
  ephemeral, network-disabled, memory-capped `python:3.12-slim` containers
  as Docker-socket siblings of the backend container.
- **Deployment**: Docker Compose (`backend` + `frontend` services).

## Multi-agent pipeline

Four agents run as a LangGraph `StateGraph`, with a Postgres checkpointer:

```
Discovery -> (conditional) -> Matcher -> Writer <-> Critic -> END
   |                             |          ^          |
   | special_apply_instructions? |          +----------+
   |                             |        (revise loop, capped by
   v                             v         MAX_AUTO_REVISIONS)
  END                        (continues)
(flagged, status=pending)
```

- **Discovery**: reads the job + the candidate's profile. Determines what's
  actually applicable from the candidate's real experience/tech stack (not a
  dump of everything), and detects any custom apply instructions.
- **Matcher**: scores fit against the job's requirements, can run sandboxed
  code if it needs to verify something computationally.
- **Writer**: drafts the apply-box message. Hard rules: no company names
  (candidate's past employers or the job's), no fabricated experience, casual
  genuine-sounding opener, no em/en dashes, no formal sign-off, never implies
  a current full-time job, always includes the candidate's portfolio link in
  an obfuscated form (`domain(dot)tld` instead of a real URL) so onlinejobs.ph
  doesn't flag it as an external link. Structure for the common case (no
  custom questions): greeting -> confident capability statement -> one
  concrete, value-focused detail -- not an immediate deep dive, since the
  recruiter hasn't asked for specifics yet.
- **Critic**: reviews the draft against the same rules. Runs cheap
  deterministic checks first (dash characters, length, portfolio link
  present/correctly formatted) before any LLM call, then an LLM judgment
  pass. Loops back to the Writer with specific feedback on failure, capped at
  `MAX_AUTO_REVISIONS`.

## Human-in-the-loop

There's no LangGraph `interrupt()` in this design -- the graph runs start to
finish in one call. Human review is a set of plain REST endpoints acting
directly on a letter's row, so status can move freely in any direction
(`pending` / `processing` / `drafted` / `approved` / `rejected`) at any time,
not just through a fixed approve/reject flow:

- A flagged (`pending`) job can be reviewed, given feedback, and drafted via
  `POST /letters/{id}/continue` -- this is a fresh run through Matcher, then
  Writer/Critic.
- Any existing letter's status can be changed via `PATCH /letters/{id}`.
  Setting it to `rejected` reuses the already-computed `job_context` /
  `fit_assessment` and kicks off a background Writer/Critic redraft with the
  human's feedback folded in -- Discovery and Matcher aren't rerun.
- All of the above run as FastAPI `BackgroundTasks`; the letter's status is
  set to `processing` synchronously before the endpoint returns, so the
  frontend can poll and reflect in-flight state without blocking on a
  20-90s LLM pipeline run.

## Observability

Every LLM call and tool call is logged (`llm_calls`, `tool_calls`): agent,
model, input/output/cached tokens, estimated cost, duration, status. The
frontend's Usage tab surfaces this per-call and aggregated by agent.
