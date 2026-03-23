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
        candidate = text[:last_complete + 1].rstrip().rstrip(",")
        # Try closing as array
        for suffix in ["]", "]}"):
            attempt = candidate + suffix
            try:
                result = json.loads(attempt)
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
            context, len(result),
        )
        return result
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in {context}: {e}. Response: {cleaned[:200]}")


def extract_gemini_tokens(response) -> tuple[int, int]:
    """Extract input/output token counts from Gemini response."""
    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    return input_tokens, output_tokens
