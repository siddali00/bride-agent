import asyncio
import logging

from app.clients.hubspot import HubspotClient
from app.clients.jira import JiraClient
from app.clients.teams import TeamsClient
from app.llm import dedupe, extract
from app.models import Draft, DraftDecision, EnrichedRequest, TeamsMessage

log = logging.getLogger(__name__)

MAX_CONCURRENCY = 5


async def run(
    teams: TeamsClient,
    jira: JiraClient,
    hubspot: HubspotClient,
    *,
    limit: int = 50,
) -> list[Draft]:
    """Fetch messages → extract → enrich → dedupe → return drafts (unsubmitted)."""
    messages = await teams.fetch_messages(top=limit)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _one(msg: TeamsMessage) -> Draft | None:
        async with sem:
            return await _process_message(msg, jira, hubspot)

    results = await asyncio.gather(*[_one(m) for m in messages], return_exceptions=False)
    return [r for r in results if r is not None]


async def _process_message(
    msg: TeamsMessage, jira: JiraClient, hubspot: HubspotClient
) -> Draft | None:
    try:
        extracted = await extract.extract(msg)
    except Exception as e:
        log.warning("extract.failed", extra={"msg_id": msg.id, "err": str(e)})
        return Draft(
            id=msg.id,
            source=EnrichedRequest(
                message_id=msg.id,
                requester=msg.sender,
                raw_client_name=None,
                matched_client_name=None,
                arr_usd=None,
                core_request=msg.text[:200],
            ),
            decision=DraftDecision(action="skip", reasoning="extract_failed"),
            error=f"extract: {e}",
        )

    if not extracted.is_feature_request:
        return None  # noise: drop silently

    # HubSpot + Jira candidate fetch can happen concurrently.
    company_task = (
        hubspot.find_company(extracted.client_name) if extracted.client_name else _none()
    )
    candidates_task = jira.search_candidates(extracted.core_request)
    company, candidates = await asyncio.gather(company_task, candidates_task)

    enriched = EnrichedRequest(
        message_id=msg.id,
        requester=extracted.requester or msg.sender,
        raw_client_name=extracted.client_name,
        matched_client_name=HubspotClient.extract_name(company),
        arr_usd=HubspotClient.extract_arr(company),
        core_request=extracted.core_request,
    )

    try:
        decision = await dedupe.decide(enriched, candidates)
    except Exception as e:
        log.warning("decide.failed", extra={"msg_id": msg.id, "err": str(e)})
        return Draft(
            id=msg.id,
            source=enriched,
            decision=DraftDecision(action="skip", reasoning="decide_failed"),
            error=f"decide: {e}",
        )

    # Defensive: if LLM picked "comment" but target key is not among candidates,
    # downgrade to "create" rather than trusting a hallucinated key.
    if decision.action == "comment":
        known = {c.key for c in candidates}
        if not decision.target_ticket_key or decision.target_ticket_key not in known:
            decision = DraftDecision(
                action="create",
                title=decision.title or enriched.core_request[:80],
                summary=decision.summary or _fallback_summary(enriched),
                reasoning="downgraded: LLM referenced unknown ticket key",
            )

    return Draft(id=msg.id, source=enriched, decision=decision)


async def _none():
    return None


def _fallback_summary(e: EnrichedRequest) -> str:
    arr = f"${e.arr_usd:,.0f}" if e.arr_usd is not None else "unknown"
    client = e.matched_client_name or e.raw_client_name or "unknown client"
    return (
        f"**Client:** {client}  \n"
        f"**ARR:** {arr}  \n"
        f"**Requested by:** {e.requester or 'unknown'} (via Teams)\n\n"
        f"{e.core_request}"
    )
