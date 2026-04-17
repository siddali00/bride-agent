import logging

from app.clients.jira import JiraClient
from app.clients.teams import TeamsClient
from app.models import Draft, SubmitResult

log = logging.getLogger(__name__)


async def submit(draft: Draft, jira: JiraClient, teams: TeamsClient) -> SubmitResult:
    """Execute one approved draft: write to Jira, then echo to Teams."""
    d = draft.decision
    if d.action == "skip":
        return SubmitResult(draft_id=draft.id, status="skipped", detail=d.reasoning)

    try:
        if d.action == "create":
            if not d.title or not d.summary:
                raise ValueError("create draft missing title/summary")
            key = await jira.create_issue(d.title, d.summary)
            feedback = _feedback_create(key, draft)
        else:  # comment
            if not d.target_ticket_key or not d.comment_body:
                raise ValueError("comment draft missing target/body")
            key = d.target_ticket_key
            await jira.add_comment(key, d.comment_body)
            feedback = _feedback_comment(key, draft)

        teams_id = await teams.post_message(feedback)
        return SubmitResult(
            draft_id=draft.id,
            status="submitted",
            jira_key=key,
            teams_message_id=teams_id,
            detail=feedback,
        )
    except Exception as e:
        log.exception("submit.failed", extra={"draft_id": draft.id})
        return SubmitResult(draft_id=draft.id, status="error", detail=str(e))


def _feedback_create(key: str, draft: Draft) -> str:
    s = draft.source
    client = s.matched_client_name or s.raw_client_name or "unknown client"
    arr_part = f" (${s.arr_usd:,.0f} ARR)" if s.arr_usd is not None else ""
    return f"Got it! Created new Ticket #{key} for {client}{arr_part}."


def _feedback_comment(key: str, draft: Draft) -> str:
    return f"Got it! Added this to Ticket #{key}."
