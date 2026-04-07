import json
import logging

logger = logging.getLogger(__name__)


def strip_markdown_fence(text: str) -> str:
    """Remove markdown code block fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        # Remove closing fence if present
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].strip()
    return text


def _repair_truncated_json(text: str) -> dict | list:
    """Repair truncated JSON by finding the last complete object and closing brackets."""
    last_complete = text.rfind("}")
    while last_complete > 0:
        candidate = text[: last_complete + 1].rstrip().rstrip(",")

        # Count unmatched brackets to build the right closing suffix
        open_brackets: list[str] = []
        in_string = False
        escape = False
        for ch in candidate:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ("{", "["):
                open_brackets.append(ch)
            elif ch == "}" and open_brackets and open_brackets[-1] == "{":
                open_brackets.pop()
            elif ch == "]" and open_brackets and open_brackets[-1] == "[":
                open_brackets.pop()

        # Build closing suffix from remaining open brackets (reversed)
        close_map = {"{": "}", "[": "]"}
        suffix = "".join(close_map[b] for b in reversed(open_brackets))

        if suffix:
            attempt = candidate + suffix
            try:
                result = json.loads(attempt)
                if isinstance(result, (list, dict)):
                    return result
            except json.JSONDecodeError:
                pass

        # Also try without suffix (candidate might already be complete)
        try:
            result = json.loads(candidate)
            if isinstance(result, (list, dict)):
                return result
        except json.JSONDecodeError:
            pass

        last_complete = text.rfind("}", 0, last_complete)
    raise json.JSONDecodeError("Could not repair JSON", text, 0)


def parse_json_response(text: str, context: str = "") -> dict | list:
    """Strip markdown fences and parse JSON from LLM response."""
    cleaned = strip_markdown_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try repairing truncated JSON array
    try:
        result = _repair_truncated_json(cleaned)
        logger.warning(
            "Repaired truncated JSON in %s — recovered %d segments (last segment may be lost)",
            context,
            len(result),
        )
        return result
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in {context}: {e}. Response: {cleaned[:200]}")


async def fetch_ollama_models(base_url: str, timeout: float = 5.0) -> list[str]:
    """GET {base_url}/api/tags and return the list of installed model names.

    Returns an empty list if the server is unreachable or returns non-200 — the
    caller decides whether that's fatal.
    """
    import httpx

    url = _resolve_ollama_url(base_url.rstrip("/"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url}/api/tags")
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    return [m.get("name", "") for m in resp.json().get("models", [])]


def _resolve_ollama_url(url: str) -> str:
    """In Docker, rewrite localhost URLs to host.docker.internal."""
    from pathlib import Path
    from urllib.parse import urlsplit, urlunsplit

    if not Path("/.dockerenv").exists():
        return url

    parts = urlsplit(url)
    if parts.hostname not in ("localhost", "127.0.0.1"):
        return url

    netloc = "host.docker.internal"
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def create_openai_compatible_client(provider: str, credential: str):
    """Create an AsyncOpenAI client for OpenAI or Ollama (OpenAI-compatible)."""
    import openai

    if provider == "ollama":
        base = _resolve_ollama_url(credential.rstrip("/"))
        if base.endswith("/v1"):
            base = base[:-3]
        return openai.AsyncOpenAI(base_url=f"{base}/v1", api_key="ollama")
    return openai.AsyncOpenAI(api_key=credential)


def extract_gemini_tokens(response) -> tuple[int, int]:
    """Extract input/output token counts from Gemini response."""
    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    return input_tokens, output_tokens
