import base64
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.models import JiraCandidate

log = logging.getLogger(__name__)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with", "is",
    "are", "be", "our", "their", "they", "them", "we", "us", "you", "please",
    "want", "wants", "need", "needs", "would", "like", "asking", "asked", "can",
    "could", "should", "client", "customer",
}


def _basic_auth() -> str:
    raw = f"{settings.jira_email}:{settings.jira_token}".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


def _keywords(text: str, limit: int = 5) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z-]{2,}", text.lower())
    seen: list[str] = []
    for t in tokens:
        if t in _STOPWORDS or t in seen:
            continue
        seen.append(t)
        if len(seen) >= limit:
            break
    return seen


class JiraClient:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    def _headers(self) -> dict[str, str]:
        return {"Authorization": _basic_auth(), "Accept": "application/json"}

    async def search_candidates(self, request_text: str, limit: int = 8) -> list[JiraCandidate]:
        """Find Jira tickets that might be duplicates of `request_text`.

        Uses a JQL keyword query over text; returns top candidates for the
        LLM to judge. Falls back to listing recent tickets if no keywords
        produce matches — the LLM is still the final arbiter.
        """
        kws = _keywords(request_text)
        jql_parts = [f'project = {settings.jira_project_key}']
        if kws:
            # OR-joined text search — broad net, LLM filters.
            text_clause = " OR ".join(f'text ~ "{k}"' for k in kws)
            jql_parts.append(f"({text_clause})")
        jql = " AND ".join(jql_parts)
        r = await self._http.get(
            f"{settings.mock_base_url}/jira/rest/api/3/search",
            headers=self._headers(),
            params={"jql": jql, "maxResults": limit},
        )
        r.raise_for_status()
        issues = r.json().get("issues", [])
        if not issues and kws:
            # Fallback: grab recent tickets so dedup still has candidates.
            r = await self._http.get(
                f"{settings.mock_base_url}/jira/rest/api/3/search",
                headers=self._headers(),
                params={"jql": f"project = {settings.jira_project_key}", "maxResults": limit},
            )
            r.raise_for_status()
            issues = r.json().get("issues", [])
        return [_coerce_candidate(i) for i in issues]

    async def create_issue(self, title: str, description_markdown: str) -> str:
        """Create a Story. Returns the new ticket key (e.g. 'JIRA-1203')."""
        payload = {
            "fields": {
                "project": {"key": settings.jira_project_key},
                "summary": title[:240],
                "description": description_markdown,
                "issuetype": {"name": "Story"},
            }
        }
        r = await self._http.post(
            f"{settings.mock_base_url}/jira/rest/api/3/issue",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        return r.json()["key"]

    async def add_comment(self, key: str, body: str) -> str:
        r = await self._http.post(
            f"{settings.mock_base_url}/jira/rest/api/3/issue/{key}/comment",
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()["id"]


def _coerce_candidate(raw: dict[str, Any]) -> JiraCandidate:
    fields = raw.get("fields") or {}
    desc = fields.get("description") or ""
    if isinstance(desc, dict):
        # ADF → flatten text nodes.
        desc = _flatten_adf(desc)
    return JiraCandidate(
        key=str(raw.get("key") or raw.get("id")),
        summary=str(fields.get("summary") or ""),
        description=str(desc),
    )


def _flatten_adf(node: dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text") or "")
    return " ".join(_flatten_adf(c) for c in node.get("content", []) if isinstance(c, dict))
