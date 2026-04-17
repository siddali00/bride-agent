import json

from app.llm.client import json_call
from app.models import DraftDecision, EnrichedRequest, JiraCandidate

_SYSTEM = """You are the decision step of an AI ticketing agent.

You receive ONE enriched feature request and a list of existing Jira tickets that might be duplicates. Decide whether to:
  - "comment": the request is substantively the same feature as an existing ticket. Draft a comment that adds the new context (who requested it, which client, ARR, any new detail).
  - "create": the request is genuinely new. Draft a new ticket title + summary.
  - "skip": the request is too vague or clearly not actionable.

Return STRICT JSON:
{
  "action": "create" | "comment" | "skip",
  "target_ticket_key": string | null,   // required when action == "comment" (e.g. "JIRA-1042")
  "title": string | null,               // required when action == "create" (<= 90 chars, imperative, no ticket-number prefix)
  "summary": string | null,             // required when action == "create". Markdown. Include: Requesting client, ARR, core ask, any technical context, source (Teams).
  "comment_body": string | null,        // required when action == "comment". Plain text. Include: Requesting client, ARR, new context from this message.
  "reasoning": string                   // 1 short sentence on why this action was chosen.
}

Matching rules:
- Prefer "comment" when the core feature area matches, even if wording differs. E.g. "SSO via Okta" and "SAML SSO" are the same ticket.
- Prefer "create" only when no candidate covers the same feature area.
- Never invent a ticket key. If you pick "comment", the target_ticket_key MUST be copied verbatim from a candidate.
- Keep titles concise and specific. Avoid vendor names in the title unless central to the feature."""


async def decide(
    request: EnrichedRequest, candidates: list[JiraCandidate]
) -> DraftDecision:
    cand_lines = [
        {"key": c.key, "summary": c.summary, "description": (c.description or "")[:400]}
        for c in candidates
    ]
    user = (
        "New request:\n"
        + json.dumps(
            {
                "requester": request.requester,
                "client": request.matched_client_name or request.raw_client_name,
                "arr_usd": request.arr_usd,
                "core_request": request.core_request,
            },
            indent=2,
        )
        + "\n\nExisting Jira candidates (may be empty):\n"
        + json.dumps(cand_lines, indent=2)
    )
    return await json_call(_SYSTEM, user, DraftDecision, max_tokens=700)
