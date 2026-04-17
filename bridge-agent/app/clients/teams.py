import logging
from typing import Any

import httpx

from app.config import settings
from app.models import TeamsMessage

log = logging.getLogger(__name__)


class TeamsClient:
    """Thin async wrapper around the mock Microsoft Graph Teams API."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http
        self._access_token: str | None = None

    async def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token
        r = await self._http.post(
            f"{settings.mock_base_url}/auth/teams/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "bridge-agent",
                "client_secret": settings.teams_client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        r.raise_for_status()
        self._access_token = r.json()["access_token"]
        log.info("teams.token_exchanged")
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._ensure_token()}"}

    async def fetch_messages(self, top: int = 50) -> list[TeamsMessage]:
        """Fetch messages from the #feature-requests channel, newest first.

        The mock returns `{id, sender, text}`-shaped records inside the
        Graph-style `value` array.
        """
        url = (
            f"{settings.mock_base_url}/graph/v1.0/teams/{settings.teams_team_id}"
            f"/channels/{settings.teams_channel_id}/messages"
        )
        r = await self._http.get(url, params={"$top": top}, headers=await self._headers())
        r.raise_for_status()
        out: list[TeamsMessage] = []
        for m in r.json().get("value", []):
            out.append(_coerce_message(m))
        log.info("teams.fetched", extra={"count": len(out)})
        return out

    async def post_message(self, content: str) -> str:
        """Post a plaintext message to the channel. Returns the new message id."""
        url = (
            f"{settings.mock_base_url}/graph/v1.0/teams/{settings.teams_team_id}"
            f"/channels/{settings.teams_channel_id}/messages"
        )
        r = await self._http.post(
            url,
            headers=await self._headers(),
            json={"body": {"contentType": "text", "content": content}},
        )
        r.raise_for_status()
        return r.json()["id"]


def _coerce_message(raw: dict[str, Any]) -> TeamsMessage:
    """The mock channel fixture uses a simple shape, but a defensive
    coercion keeps us safe if the mock is swapped for a real Graph response
    shape (body.content / from.user.displayName)."""
    msg_id = str(raw.get("id"))
    sender = raw.get("sender") or (
        raw.get("from", {}).get("user", {}).get("displayName") if isinstance(raw.get("from"), dict) else None
    )
    text = raw.get("text")
    if text is None:
        body = raw.get("body") or {}
        text = body.get("content") if isinstance(body, dict) else None
    return TeamsMessage(id=msg_id, sender=sender or "unknown", text=text or "")
