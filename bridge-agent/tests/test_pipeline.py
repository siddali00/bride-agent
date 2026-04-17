"""End-to-end test for the orchestration pipeline.

We mock every outbound HTTP call with httpx.MockTransport and monkeypatch
the two LLM calls so the test runs offline with no API keys required.
"""
from __future__ import annotations

import httpx
import pytest

from app.clients.hubspot import HubspotClient
from app.clients.jira import JiraClient
from app.clients.teams import TeamsClient
from app.models import DraftDecision, ExtractedRequest


def _mock_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("/auth/teams/token"):
        return httpx.Response(200, json={"access_token": "fake-teams", "expires_in": 3600})
    if "graph/v1.0/teams" in url and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "value": [
                    {"id": "m1", "sender": "alice", "text": "Hooli wants SSO via Okta."},
                    {"id": "m2", "sender": "bob", "text": "Wifi is flaky again, argh."},
                ]
            },
        )
    if "graph/v1.0/teams" in url and request.method == "POST":
        return httpx.Response(201, json={"id": "posted-1"})
    if "hubspot/crm/v3/objects/companies/search" in url:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "1",
                        "properties": {
                            "name": "Hooli Inc.",
                            "annual_recurring_revenue": "520000",
                        },
                    }
                ]
            },
        )
    if "jira/rest/api/3/search" in url:
        return httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "JIRA-1042",
                        "fields": {
                            "summary": "Implement SAML SSO",
                            "description": "Enterprise SSO via SAML",
                        },
                    }
                ]
            },
        )
    if "jira/rest/api/3/issue" in url and request.method == "POST" and "/comment" not in url:
        return httpx.Response(201, json={"key": "JIRA-1203", "id": "1203"})
    if "/comment" in url and request.method == "POST":
        return httpx.Response(201, json={"id": "c1"})
    return httpx.Response(404, json={"detail": f"unmocked: {url}"})


@pytest.mark.asyncio
async def test_pipeline_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub the two LLM calls so we don't need a real API key.
    async def fake_extract(msg):
        if "wifi" in msg.text.lower():
            return ExtractedRequest(is_feature_request=False, core_request="")
        return ExtractedRequest(
            is_feature_request=True,
            requester=msg.sender,
            client_name="Hooli",
            core_request="SSO via Okta",
        )

    async def fake_decide(request, candidates):
        # Always match the SAML SSO candidate → comment action.
        return DraftDecision(
            action="comment",
            target_ticket_key="JIRA-1042",
            comment_body="New request from Hooli via alice on Teams.",
            reasoning="same feature area as JIRA-1042",
        )

    from app import pipeline
    from app.llm import dedupe, extract

    monkeypatch.setattr(extract, "extract", fake_extract)
    monkeypatch.setattr(dedupe, "decide", fake_decide)
    # also patch the names inside the pipeline module's namespace
    monkeypatch.setattr(pipeline.extract, "extract", fake_extract)
    monkeypatch.setattr(pipeline.dedupe, "decide", fake_decide)

    # Config needs these env vars to construct Settings — inject minimum set.
    for k, v in {
        "OPENROUTER_API_KEY": "test",
        "JIRA_EMAIL": "t@example.com",
        "JIRA_TOKEN": "jira-token-test",
        "HUBSPOT_TOKEN": "hs-pat-test",
        "TEAMS_CLIENT_SECRET": "teams-secret-test",
    }.items():
        monkeypatch.setenv(k, v)

    transport = httpx.MockTransport(_mock_handler)
    async with httpx.AsyncClient(transport=transport) as http:
        teams = TeamsClient(http)
        jira = JiraClient(http)
        hubspot = HubspotClient(http)
        drafts = await pipeline.run(teams, jira, hubspot, limit=10)

    # wifi message was dropped as noise; SSO message produced a "comment" draft.
    assert len(drafts) == 1
    d = drafts[0]
    assert d.decision.action == "comment"
    assert d.decision.target_ticket_key == "JIRA-1042"
    assert d.source.matched_client_name == "Hooli Inc."
    assert d.source.arr_usd == 520000.0
