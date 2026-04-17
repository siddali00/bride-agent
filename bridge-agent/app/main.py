import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import pipeline, submitter
from app.clients.hubspot import HubspotClient
from app.clients.jira import JiraClient
from app.clients.teams import TeamsClient
from app.models import Draft, SubmitResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    transport = httpx.AsyncHTTPTransport(retries=2)
    async with httpx.AsyncClient(timeout=30.0, transport=transport) as http:
        app.state.http = http
        app.state.teams = TeamsClient(http)
        app.state.jira = JiraClient(http)
        app.state.hubspot = HubspotClient(http)
        yield


app = FastAPI(title="WorkFlex Bridge Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


class ProcessResponse(BaseModel):
    drafts: list[Draft]


@app.post("/api/process", response_model=ProcessResponse)
async def api_process() -> ProcessResponse:
    drafts = await pipeline.run(app.state.teams, app.state.jira, app.state.hubspot)
    return ProcessResponse(drafts=drafts)


class SubmitRequest(BaseModel):
    drafts: list[Draft]


class SubmitResponse(BaseModel):
    results: list[SubmitResult]


@app.post("/api/submit", response_model=SubmitResponse)
async def api_submit(payload: SubmitRequest) -> SubmitResponse:
    if not payload.drafts:
        raise HTTPException(status_code=400, detail="no drafts to submit")
    results: list[SubmitResult] = []
    for d in payload.drafts:
        results.append(await submitter.submit(d, app.state.jira, app.state.teams))
    return SubmitResponse(results=results)
