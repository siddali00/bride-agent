from typing import Literal
from pydantic import BaseModel, Field


class TeamsMessage(BaseModel):
    id: str
    sender: str
    text: str


class ExtractedRequest(BaseModel):
    is_feature_request: bool
    requester: str | None = None
    client_name: str | None = None
    core_request: str = ""


class JiraCandidate(BaseModel):
    key: str
    summary: str
    description: str = ""


class EnrichedRequest(BaseModel):
    message_id: str
    requester: str | None
    raw_client_name: str | None
    matched_client_name: str | None
    arr_usd: float | None
    core_request: str


class DraftDecision(BaseModel):
    action: Literal["create", "comment", "skip"]
    target_ticket_key: str | None = None
    title: str | None = None
    summary: str | None = None
    comment_body: str | None = None
    reasoning: str = ""


class Draft(BaseModel):
    id: str = Field(description="stable id = source message id")
    source: EnrichedRequest
    decision: DraftDecision
    error: str | None = None


class SubmitResult(BaseModel):
    draft_id: str
    status: Literal["submitted", "skipped", "error"]
    jira_key: str | None = None
    teams_message_id: str | None = None
    detail: str = ""
