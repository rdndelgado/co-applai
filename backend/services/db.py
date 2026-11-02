from datetime import datetime, timedelta, timezone

from supabase import create_client

from core import constants

_client = None


def get_client():
    global _client
    if _client is None:
        _client = create_client(constants.SUPABASE_URL, constants.SUPABASE_KEY)
    return _client


def fetch_unlettered_jobs(limit):
    """Jobs with status=done that either have no letter yet, or whose letter
    was rejected (due for a redraft). Capped at `limit`."""
    client = get_client()

    done_jobs = (
        client.table(constants.JOBS_TABLE_NAME)
        .select("*")
        .eq("status", "done")
        .execute()
        .data
    )
    if not done_jobs:
        return []

    letters = client.table("letters").select("job_id,status").execute().data
    excluded = {row["job_id"] for row in letters if row["status"] != "rejected"}

    candidates = [job for job in done_jobs if job["id"] not in excluded]
    return candidates[:limit]


def list_jobs(keyword=None, job_type=None, status=None, flags=None):
    """All scraped jobs, joined with their letter (if any). `status` filters
    on the letter's status -- "none" means jobs with no letter row at all.
    Sorted by whichever is most recent: the letter's last update (draft/
    approve/reject/redraft) if one exists, else the job's own scrape time --
    so anything you just acted on floats to the top."""
    client = get_client()
    query = client.table(constants.JOBS_TABLE_NAME).select("*")
    if keyword:
        query = query.eq("keyword", keyword)
    if job_type:
        query = query.eq("job_type", job_type)
    jobs = query.execute().data

    letters = (
        client.table("letters").select("id,job_id,status,job_context,updated_at").execute().data
    )
    letters_by_job = {row["job_id"]: row for row in letters}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=constants.OLD_JOB_THRESHOLD_DAYS)).isoformat()

    results = []
    for job in jobs:
        letter = letters_by_job.get(job["id"])
        letter_status = letter["status"] if letter else None
        if status and status != (letter_status or "none"):
            continue
        job_context = (letter or {}).get("job_context")
        job["letter_id"] = letter["id"] if letter else None
        job["letter_status"] = letter_status
        job["letter_updated_at"] = (letter or {}).get("updated_at")
        job["flagged"] = bool(job_context and job_context.get("special_apply_instructions"))
        job["job_context"] = job_context

        # staleness of the posting itself, not when we happened to scrape it
        # -- created_at is always recent (scrape time) so including it here
        # would mask every stale posting
        date_updated = job.get("date_updated")
        job["is_old"] = bool(date_updated) and date_updated < cutoff

        if flags:
            job_flags = set()
            if job["flagged"]:
                job_flags.add("custom")
            if job["is_old"]:
                job_flags.add("old")
            if not job_flags:
                job_flags.add("none")
            # exact match only -- a job with both custom+old flags matches
            # neither the "custom" nor the "old" filter on its own
            if len(job_flags) != 1 or not job_flags <= set(flags):
                continue

        results.append(job)

    results.sort(key=lambda j: j["letter_updated_at"] or j.get("created_at") or "", reverse=True)

    return results


def list_job_filter_options():
    rows = (
        get_client()
        .table(constants.JOBS_TABLE_NAME)
        .select("keyword,job_type")
        .execute()
        .data
    )
    keywords = sorted({r["keyword"] for r in rows if r.get("keyword")})
    job_types = sorted({r["job_type"] for r in rows if r.get("job_type")})
    return {"keywords": keywords, "job_types": job_types}


def get_job(job_id):
    response = (
        get_client()
        .table(constants.JOBS_TABLE_NAME)
        .select("*")
        .eq("id", job_id)
        .single()
        .execute()
    )
    return response.data


def ensure_letter_row(job_id):
    client = get_client()
    existing = (
        client.table("letters").select("*").eq("job_id", job_id).execute().data
    )
    if existing:
        return existing[0]

    response = client.table("letters").insert({"job_id": job_id}).execute()
    return response.data[0]


def get_letter(letter_id):
    response = (
        get_client()
        .table("letters")
        .select("*, jobs(title,url,job_type,rate,date_updated)")
        .eq("id", letter_id)
        .single()
        .execute()
    )
    return response.data


def get_letter_by_job(job_id):
    response = (
        get_client().table("letters").select("*").eq("job_id", job_id).execute()
    )
    return response.data[0] if response.data else None


def list_letters(status=None):
    query = get_client().table("letters").select(
        "*, jobs(title,url,job_type,rate,date_updated)"
    )
    if status:
        query = query.eq("status", status)
    return query.order("updated_at", desc=True).execute().data


def update_letter(letter_id, fields):
    # no DB trigger for this -- every write bumps it here, so "last touched"
    # (draft/approve/reject/redraft) is always accurate for sorting
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    get_client().table("letters").update(fields).eq("id", letter_id).execute()


def insert_llm_call(row):
    get_client().table("llm_calls").insert(row).execute()


def list_llm_calls(limit=200):
    return (
        get_client()
        .table("llm_calls")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


def insert_tool_call(row):
    get_client().table("tool_calls").insert(row).execute()


def count_llm_calls_since(since_iso):
    response = (
        get_client()
        .table("llm_calls")
        .select("id", count="exact")
        .gte("created_at", since_iso)
        .execute()
    )
    return response.count or 0
