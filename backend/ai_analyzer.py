"""Direct Google Gemini cost analysis. Non-agentic: one generate_content call, no tools."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

DEFAULT_MODEL = "gemini-3.8-flash"
MAX_PROMPT_RESOURCES = 250

# Application-level retries after the first request. The google-genai SDK does
# not retry by default (HttpRetryOptions is unset → one attempt), so this loop
# is the only retry layer.
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 8.0
REQUEST_TIMEOUT_MS = 60_000
TRANSIENT_UNAVAILABLE_MESSAGE = (
    "Gemini AI service is temporarily unavailable. Please try again later."
)
RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
RETRYABLE_STATUS_NAMES = {
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "DEADLINE_EXCEEDED",
    "ABORTED",
}
PERMANENT_HTTP_CODES = {400, 401, 403, 404, 422}

_log = logging.getLogger(__name__)


class GeminiAnalyzerError(Exception):
    def __init__(self, message: str, code: str = "GEMINI_ERROR", status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class GeminiNotConfiguredError(GeminiAnalyzerError):
    def __init__(self, message: str = "GEMINI_API_KEY is not set."):
        super().__init__(message, code="GEMINI_NOT_CONFIGURED", status_code=500)


class GeminiApiError(GeminiAnalyzerError):
    def __init__(self, message: str):
        super().__init__(message, code="GEMINI_API_ERROR", status_code=502)


class GeminiResponseError(GeminiAnalyzerError):
    def __init__(self, message: str):
        super().__init__(message, code="GEMINI_RESPONSE_ERROR", status_code=502)


def _api_key() -> str:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise GeminiNotConfiguredError(
            "GEMINI_API_KEY is not configured. Set it in the backend environment."
        )
    return key


def _model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _redact_secrets(text: str) -> str:
    redacted = text
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if key:
        redacted = redacted.replace(key, "[redacted]")
    return redacted


def _is_timeout_or_network_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name:
        return True
    lowered = str(exc).lower()
    return any(
        token in lowered
        for token in ("timed out", "timeout", "connection reset", "connection aborted", "temporarily unreachable")
    )


def _is_permanent_gemini_error(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        code = int(exc.code or 0)
        if code in PERMANENT_HTTP_CODES:
            return True
        if 400 <= code < 500 and code not in RETRYABLE_HTTP_CODES:
            return True
        status = str(exc.status or "").upper()
        if status in {"UNAUTHENTICATED", "PERMISSION_DENIED", "INVALID_ARGUMENT", "NOT_FOUND", "FAILED_PRECONDITION"}:
            return True
    lowered = _redact_secrets(str(exc)).lower()
    if any(
        token in lowered
        for token in ("api key", "invalid api key", "permission_denied", "unauthenticated", "invalid_argument")
    ):
        return True
    return False


def _is_transient_gemini_error(exc: BaseException) -> bool:
    if _is_permanent_gemini_error(exc):
        return False
    if _is_timeout_or_network_error(exc):
        return True
    if isinstance(exc, genai_errors.APIError):
        code = int(exc.code or 0)
        status = str(exc.status or "").upper()
        if code in RETRYABLE_HTTP_CODES or status in RETRYABLE_STATUS_NAMES:
            return True
        if code >= 500:
            return True
    lowered = _redact_secrets(str(exc)).upper()
    return any(
        token in lowered
        for token in (
            "503",
            "UNAVAILABLE",
            "429",
            "RESOURCE_EXHAUSTED",
            "RATE LIMIT",
            "TOO MANY REQUESTS",
        )
    )


def _backoff_seconds(retry_index: int) -> float:
    ceiling = min(MAX_BACKOFF_SECONDS, INITIAL_BACKOFF_SECONDS * (2**retry_index))
    return random.uniform(0, ceiling)


def _raise_permanent_gemini_error(exc: Exception) -> None:
    message = _redact_secrets(str(exc))
    lowered = message.lower()
    if "api key" in lowered or "permission_denied" in lowered or "401" in lowered or "unauthenticated" in lowered:
        raise GeminiApiError("Gemini rejected the API key or request authentication.") from exc
    raise GeminiApiError(f"Gemini API request failed: {message}") from exc


def _generate_content_with_retry(api_key: str, prompt: str) -> Any:
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            # Keep SDK retries off so we do not stack retries on this loop.
            retry_options=None,
        ),
    )
    last_transient: Exception | None = None
    attempts = MAX_RETRIES + 1
    for attempt in range(attempts):
        try:
            return client.models.generate_content(
                model=_model_name(),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                    system_instruction=(
                        "You analyze AWS cost waste. Reply with JSON only. "
                        "Do not execute actions. Provide AWS CLI recommendations for manual review."
                    ),
                ),
            )
        except GeminiAnalyzerError:
            raise
        except Exception as exc:
            if _is_permanent_gemini_error(exc):
                _raise_permanent_gemini_error(exc)
            if not _is_transient_gemini_error(exc):
                _raise_permanent_gemini_error(exc)
            last_transient = exc
            retries_left = MAX_RETRIES - attempt
            if retries_left <= 0:
                break
            delay = _backoff_seconds(attempt)
            _log.warning(
                "Transient Gemini error on attempt %s/%s; retrying in %.2fs.",
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)
    raise GeminiApiError(TRANSIENT_UNAVAILABLE_MESSAGE) from last_transient


def _compact_resources(resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop bulky CloudWatch metric rows so the prompt stays within model limits."""
    compact: list[dict[str, Any]] = []
    metric_count = 0
    for item in resources:
        if item.get("service") == "cloudwatch" and item.get("resource_type") == "metric":
            metric_count += 1
            continue
        compact.append(item)

    truncated = False
    if len(compact) > MAX_PROMPT_RESOURCES:
        compact = compact[:MAX_PROMPT_RESOURCES]
        truncated = True

    return compact, {
        "cloudwatch_metric_descriptors_omitted": metric_count,
        "resources_sent_to_model": len(compact),
        "truncated": truncated,
    }


def _build_prompt(scan: dict[str, Any], resources: list[dict[str, Any]], prompt_meta: dict[str, Any]) -> str:
    inventory = {
        "region": scan.get("region"),
        "account_id": scan.get("account_id"),
        "resource_count_discovered": scan.get("resource_count"),
        "counts_by_type": scan.get("counts_by_type"),
        "partial_scan_errors": scan.get("partial_errors"),
        "prompt_meta": prompt_meta,
        "resources": resources,
    }

    return f"""You are a FinOps / AWS cost-optimization analyst.

Analyze the AWS inventory JSON below. Look specifically for:
- Over-provisioning (oversized EC2/RDS instance classes, unused capacity signals)
- Unused or idle resources (unattached EBS, unassociated Elastic IPs, idle instances)
- Misconfigurations (missing S3 lifecycle rules, public RDS, Multi-AZ when unused, encryption/backup waste)
- Wrong instance types or inefficient configurations
- Storage and logging cost drivers (EBS size/type, S3 without lifecycle, CloudWatch metric volume)
- Other practical cost-optimization opportunities

Rules:
- Use only the inventory provided. Do not invent resource IDs that are not in the JSON.
- Estimates are approximate USD; state uncertainty in estimated_savings.notes.
- Never claim you stopped, deleted, or modified AWS resources.
- fix_commands must be AWS CLI commands for a human to review and run manually.
- Prefer the safest explicit commands (--dry-run where supported). Include a warning on destructive commands.
- If evidence is weak, lower severity and say so in the description.
- Return JSON only, matching the required schema.

Inventory:
{json.dumps(inventory, default=str)}
"""


def _parse_json_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiResponseError(f"Gemini returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GeminiResponseError("Gemini JSON must be an object.")
    return parsed


def _normalize_severity(value: Any) -> str:
    severity = str(value or "medium").strip().lower()
    if severity not in {"high", "medium", "low"}:
        return "medium"
    return severity


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _normalize_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    issues = []
    for index, issue in enumerate(_as_list(raw.get("issues")), start=1):
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id") or f"issue-{index}")
        issues.append(
            {
                "id": issue_id,
                "title": str(issue.get("title") or "Unnamed issue"),
                "severity": _normalize_severity(issue.get("severity")),
                "category": str(issue.get("category") or "other"),
                "resource_ids": [str(rid) for rid in _as_list(issue.get("resource_ids"))],
                "description": str(issue.get("description") or ""),
                "recommendation": str(issue.get("recommendation") or ""),
                "estimated_monthly_savings_usd": issue.get("estimated_monthly_savings_usd"),
            }
        )

    savings = raw.get("estimated_savings")
    if not isinstance(savings, dict):
        savings = {}

    commands = []
    for item in _as_list(raw.get("fix_commands")):
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        commands.append(
            {
                "issue_id": str(item.get("issue_id") or ""),
                "description": str(item.get("description") or ""),
                "command": command,
                "warning": str(
                    item.get("warning")
                    or "Review this command before running it. Nothing is applied automatically."
                ),
            }
        )

    return {
        "summary": str(raw.get("summary") or ""),
        "issues": issues,
        "estimated_savings": {
            "currency": str(savings.get("currency") or "USD"),
            "monthly_low": savings.get("monthly_low"),
            "monthly_high": savings.get("monthly_high"),
            "annual_low": savings.get("annual_low"),
            "annual_high": savings.get("annual_high"),
            "notes": str(savings.get("notes") or ""),
        },
        "fix_commands": commands,
    }


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "category": {"type": "string"},
                    "resource_ids": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "estimated_monthly_savings_usd": {"type": "number"},
                },
                "required": ["id", "title", "severity", "description", "recommendation"],
            },
        },
        "estimated_savings": {
            "type": "object",
            "properties": {
                "currency": {"type": "string"},
                "monthly_low": {"type": "number"},
                "monthly_high": {"type": "number"},
                "annual_low": {"type": "number"},
                "annual_high": {"type": "number"},
                "notes": {"type": "string"},
            },
        },
        "fix_commands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string"},
                    "description": {"type": "string"},
                    "command": {"type": "string"},
                    "warning": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    "required": ["summary", "issues", "estimated_savings", "fix_commands"],
}


def analyze_resources(scan: dict[str, Any]) -> dict[str, Any]:
    """Call Gemini once with the discovered inventory and return structured analysis."""
    api_key = _api_key()
    resources = scan.get("resources") or []
    if not isinstance(resources, list):
        resources = []

    compact, prompt_meta = _compact_resources(resources)
    prompt = _build_prompt(scan, compact, prompt_meta)

    try:
        response = _generate_content_with_retry(api_key, prompt)
    except GeminiAnalyzerError:
        raise

    text = getattr(response, "text", None)
    if not text:
        raise GeminiResponseError("Gemini returned an empty analysis.")

    normalized = _normalize_analysis(_parse_json_text(text))
    normalized["model"] = _model_name()
    normalized["disclaimer"] = (
        "Recommendations and AWS CLI commands are suggestions only. "
        "This service does not modify AWS resources."
    )
    return normalized
