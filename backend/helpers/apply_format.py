import re


def obfuscate_link(url):
    """Strips the scheme and replaces every "." with "(dot)" so job-board
    link filters (which flag/strip raw URLs in applicant messages) don't
    catch it. Computed once here, deterministically -- not left to the model
    to format consistently on its own."""
    stripped = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    return stripped.replace(".", "(dot)")


def is_short_format(job_context):
    """True when there are no explicit questions to answer -- the standard
    short hook-message format applies, even if there's a simple opening-word
    or attachment requirement layered on top of it. False only when the job
    posting has actual questions the applicant must answer, which need real
    room to answer properly."""
    special = job_context.get("special_apply_instructions") or {}
    return not (special.get("questions") or [])


def format_special_instructions(special):
    """Human-readable rendering of a flagged job's custom apply instructions,
    written into letters.content while status=pending -- so a flagged job
    shows the actual rules (not a blank draft) wherever content is displayed,
    and your feedback has something concrete to respond to."""
    lines = []

    if special.get("must_start_with"):
        lines.append(f'Must start the message with: "{special["must_start_with"]}"')

    if special.get("questions"):
        lines.append("")
        lines.append("Questions to answer:")
        for q in special["questions"]:
            lines.append(f"- {q}")

    if special.get("requires_attachment"):
        lines.append("")
        lines.append(f"Attachment requested: {special.get('attachment_note') or '(unspecified)'}")

    if special.get("raw_instructions"):
        lines.append("")
        lines.append("Raw instructions from the posting:")
        lines.append(special["raw_instructions"])

    return "\n".join(lines).strip()
