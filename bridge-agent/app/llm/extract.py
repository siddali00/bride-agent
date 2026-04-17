from app.llm.client import json_call
from app.models import ExtractedRequest, TeamsMessage

_SYSTEM = """You triage internal Microsoft Teams messages from a B2B SaaS company.

For each message, decide whether it contains an actionable customer/product feature request that should become (or update) a Jira ticket.

Return STRICT JSON matching:
{
  "is_feature_request": bool,     // false for internal chatter: wifi, coffee, birthdays, retros, CI/CD gripes, etc.
  "requester": string | null,     // the Teams sender (the internal employee relaying the request)
  "client_name": string | null,   // the CUSTOMER company mentioned (e.g. "Hooli", "Initech"). null if none mentioned.
  "core_request": string          // one short sentence, normalized, stating what the client wants. "" if not a request.
}

Rules:
- If the message is internal banter with no customer and no feature ask, set is_feature_request=false and leave client_name null.
- Extract the CUSTOMER name, not the internal sender's company.
- Strip suffixes from client_name when possible ("Hooli Inc." -> "Hooli"), but keep distinctive words.
- Do not invent information. If the client is not named, leave client_name null but still set is_feature_request based on whether a real ask is present."""


async def extract(msg: TeamsMessage) -> ExtractedRequest:
    user = f"Sender: {msg.sender}\n\nMessage:\n{msg.text}"
    return await json_call(_SYSTEM, user, ExtractedRequest, max_tokens=250)
