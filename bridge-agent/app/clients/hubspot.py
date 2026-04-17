import logging
import re
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_ARR_PROPS = ["name", "domain", "annual_recurring_revenue", "annualrevenue"]


class HubspotClient:
    """Mock HubSpot CRM v3 wrapper with a small fuzzy-match shim.

    The mock accepts a free-text `query` that matches name or domain
    case-insensitively. Our Teams messages mention clients informally
    ("Hooli", "Hooli Inc.", "Hooli's"), so we normalize before querying
    and — if the first pass misses — retry with a shorter token.
    """

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.hubspot_token}",
            "Content-Type": "application/json",
        }

    async def find_company(self, raw_name: str) -> dict[str, Any] | None:
        """Return the best matching company dict, or None."""
        if not raw_name:
            return None
        cleaned = _clean_company_name(raw_name)
        if not cleaned:
            return None

        # Try exact-ish search on the full cleaned name first.
        hit = await self._search(cleaned)
        if hit:
            return hit

        # Fallback: core token only (e.g. "Hooli" from "Hooli Inc.").
        core = cleaned.split()[0]
        if core.lower() != cleaned.lower():
            hit = await self._search(core)
        return hit

    async def _search(self, query: str) -> dict[str, Any] | None:
        r = await self._http.post(
            f"{settings.mock_base_url}/hubspot/crm/v3/objects/companies/search",
            headers=self._headers(),
            json={"query": query, "limit": 5, "properties": _ARR_PROPS},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return None
        # Rank: prefer a result whose `name` starts with the query token.
        q_lower = query.lower()
        results.sort(
            key=lambda c: (
                0 if (c.get("properties", {}).get("name") or "").lower().startswith(q_lower) else 1,
                len((c.get("properties", {}).get("name") or "")),
            )
        )
        return results[0]

    @staticmethod
    def extract_arr(company: dict[str, Any] | None) -> float | None:
        if not company:
            return None
        props = company.get("properties") or {}
        raw = props.get("annual_recurring_revenue") or props.get("annualrevenue")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def extract_name(company: dict[str, Any] | None) -> str | None:
        if not company:
            return None
        return (company.get("properties") or {}).get("name")


_SUFFIXES = {"inc", "inc.", "corp", "corp.", "ltd", "llc", "gmbh", "co", "co.", "company", "'s", "the"}


def _clean_company_name(raw: str) -> str:
    s = raw.strip().strip(".,:;\"'")
    s = re.sub(r"[’']s\b", "", s)
    tokens = [t for t in re.split(r"\s+", s) if t]
    tokens = [t for t in tokens if t.lower().strip(".") not in _SUFFIXES]
    return " ".join(tokens).strip()
