"""AI provider adapters. Direct HTTP; no SDK or agent framework (Technical Spec §1)."""
import json
import re

from django.conf import settings


class ProviderError(Exception):
    pass


def extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ProviderError("The AI response was not valid JSON.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"The AI response was not valid JSON: {exc}")


def anthropic_complete(ai_settings, system, user_prompt):
    import httpx

    key = settings.AI_ANTHROPIC_API_KEY
    if not key:
        raise ProviderError("ANTHROPIC_API_KEY is not configured on the server.")
    body = {
        "model": ai_settings.model,
        "max_tokens": ai_settings.max_output_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        response = httpx.post(settings.AI_ANTHROPIC_URL, json=body, headers=headers, timeout=settings.AI_REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach the AI provider: {exc.__class__.__name__}")
    if response.status_code >= 400:
        raise ProviderError(f"AI provider returned HTTP {response.status_code}")
    data = response.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    usage = data.get("usage", {})
    return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def _sentences(text, limit=2):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(p for p in parts[:limit] if p)


def mock_complete(feature, notes, context):
    """Deterministic offline provider so the workflow can be tested without cost."""
    if feature == "summarize":
        points = []
        for n in notes[:6]:
            line = _sentences(n["text"], 1) or n["text"][:140]
            points.append(f"{n['date']} ({n['kind']}): {line}")
        latest = notes[0] if notes else None
        summary = (
            f"{len(notes)} note(s) reviewed for {context['name']}. "
            + (f"Most recent: {_sentences(latest['text'], 1)}" if latest else "")
        ).strip()
        output = {
            "summary": summary,
            "key_points": points,
            "open_questions": ["Confirm the next step and its date with the contact."],
            "source_ids": [n["id"] for n in notes[:6]],
        }
    else:
        first = context.get("contact_first_name") or "there"
        topic = context.get("topic") or "our conversation"
        recent = _sentences(notes[0]["text"], 1) if notes else ""
        body = (
            f"Hi {first},\n\n"
            f"Thank you for your time on {topic}. "
            + (f"As discussed: {recent}\n\n" if recent else "\n\n")
            + "Could you let me know a convenient time this week to take the next step?\n\n"
            f"Best regards,\n{context.get('sender_name', '')}"
        )
        output = {"subject": f"Following up - {topic}", "body": body, "source_ids": [n["id"] for n in notes[:3]]}
    text_in = sum(len(n["text"]) for n in notes)
    return output, max(1, text_in // 4), max(1, len(json.dumps(output)) // 4)
