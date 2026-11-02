import json
import re


def parse_json_response(text):
    """Strips markdown code fences if present, then parses JSON. Agents are
    prompted to respond in strict JSON, but models sometimes wrap it in
    ```json ... ``` anyway."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)
