# ERD

`schema.sql` itself is gitignored (it is applied directly in the Supabase SQL
editor and treated as local/deployment config). This doc is the committed
record of the schema shape.

co-applai shares one Supabase project with `onlinejobsph-scraper` /
`onlinejobsph-scraper-view`. It reads the `jobs` table that project owns and
adds three tables of its own: `letters`, `llm_calls`, `tool_calls`.

## Entities

```
jobs (owned by onlinejobsph-scraper)
  id               bigint PK
  url              text
  keyword          text
  status           text        -- pending | done | failed
  html_content     text
  job_id           text        -- onlinejobs.ph's own job id
  title            text
  description      text
  rate             text
  job_type         text
  date_updated     timestamptz -- posting's own last-updated date on the site
  skills           jsonb
  employer_name    text
  error_message    text
  created_at       timestamptz
  updated_at       timestamptz

letters (owned by co-applai)
  id                   bigint PK
  job_id               bigint FK -> jobs.id, unique
  job_context          jsonb       -- Discovery Agent output, computed once, reused across redrafts
  fit_assessment       jsonb       -- Matcher Agent output, computed once, reused across redrafts
  content              text        -- drafted apply-box message, or (for flagged jobs) the rendered custom rules
  status               text        -- pending | processing | drafted | approved | rejected
  rejection_feedback   text        -- human feedback on reject, folded into the next redraft
  revision_count       int         -- human reject -> redraft cycles
  auto_revision_count  int         -- Critic reject -> redraft cycles (capped by MAX_AUTO_REVISIONS)
  created_at           timestamptz
  updated_at           timestamptz -- bumped on every write, drives "most recently touched" sort

llm_calls (owned by co-applai)
  id                  bigint PK
  thread_id           text        -- langgraph thread id (= job_id for this graph)
  job_id              bigint FK -> jobs.id
  node_name           text        -- discovery | matcher | writer | critic
  model               text
  input_tokens        int
  output_tokens       int
  cached_tokens       int
  total_tokens        int
  estimated_cost_usd  numeric(10,6)
  duration_ms         int
  status              text        -- success | error
  error_message       text
  created_at          timestamptz

tool_calls (owned by co-applai)
  id             bigint PK
  thread_id      text
  job_id         bigint FK -> jobs.id
  tool_name      text        -- get_job_details | get_profile | run_sandboxed_code | save_draft
  input_summary  text
  status         text        -- success | error
  error_message  text
  duration_ms    int
  created_at     timestamptz
```

## Relationships

- `jobs 1 --- 1 letters` (unique index on `letters.job_id`): each job gets at
  most one letter row. Redrafts update the existing row rather than inserting
  a new one, so `job_context`/`fit_assessment` aren't recomputed.
- `jobs 1 --- N llm_calls` and `jobs 1 --- N tool_calls`: every agent/tool
  invocation for a job's pipeline run is logged, for the Usage tab's
  per-call observability view.
- `letters.job_id` is the join key `onlinejobsph-scraper-view` and
  `co-applai`'s frontend both use to show a job's current draft/flag state
  alongside its scrape data.
