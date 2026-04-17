"""
WorkFlex Mock API Server
========================
Simulates Jira Cloud REST API v3, HubSpot CRM API v3, and Microsoft Graph API (Teams).

Run:
    pip install -r requirements.txt
    python mock_server.py

Server starts on http://localhost:8080
Interactive API docs at http://localhost:8080/docs
"""

import json
import os
import uuid
import time
import base64
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

# ============================================================
# App Setup
# ============================================================

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080")

app = FastAPI(
    title="WorkFlex Mock API Server",
    description=(
        "Mock server simulating **Jira Cloud**, **HubSpot CRM**, and **Microsoft Teams** APIs "
        "for the WorkFlex Bridge Agent coding challenge.\n\n"
        "### Getting Started\n"
        "1. Open the [Token Dashboard](/dashboard) to generate API tokens for each service\n"
        "2. Use the tokens with each service's native auth mechanism (see endpoint docs)\n"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).parent

# ============================================================
# Constants
# ============================================================

JIRA_PROJECT_KEY = "JIRA"
JIRA_PROJECT_ID = "10001"

TEAMS_TEAM_ID = "a1b2c3d4-e5f6-7890-abcd-ef0123456789"
TEAMS_CHANNEL_ID = "19:feature-requests@thread.tacv2"
TEAMS_TENANT_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"

# ============================================================
# In-Memory Stores
# ============================================================

valid_api_keys: set[str] = set()          # legacy universal keys
jira_api_keys: set[str] = set()            # jira-only keys
hubspot_api_keys: set[str] = set()         # hubspot-only keys
teams_api_keys: set[str] = set()           # teams-only keys (client_secret)
teams_tokens: dict[str, dict] = {}         # access_token -> metadata
dashboard_tokens: dict[str, dict] = {}     # service -> latest token data for UI

jira_issues: dict[str, dict] = {}   # key_or_id -> issue
jira_comments: dict[str, list] = {} # issue_key -> [comments]
jira_next_ticket_num = 1200

hubspot_companies: dict[str, dict] = {}  # id -> company

teams_messages: dict[str, dict] = {}     # msg_id -> message
teams_replies: dict[str, list] = {}      # msg_id -> [replies]
teams_users: dict[str, str] = {}         # display_name -> user_id


# ============================================================
# Data Seeding
# ============================================================

def _to_adf(text: str) -> dict:
    """Convert plain text to Atlassian Document Format."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


def _seed_jira():
    global jira_next_ticket_num
    with open(DATA_DIR / "jira_backlog.json", encoding="utf-8") as f:
        tickets = json.load(f)

    for i, t in enumerate(tickets):
        key = t["ticket_id"]
        num = int(key.split("-")[1])
        issue_id = str(10000 + num)
        ts = datetime(2026, 3, 10, 9, 0, 0, tzinfo=timezone.utc) + timedelta(hours=i * 4)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.000+0000")

        issue = {
            "expand": "operations,versionedRepresentations,editmeta,changelog,renderedFields",
            "id": issue_id,
            "self": f"{BASE_URL}/jira/rest/api/3/issue/{issue_id}",
            "key": key,
            "fields": {
                "summary": t["title"],
                "description": _to_adf(t["description"]),
                "status": {
                    "self": f"{BASE_URL}/jira/rest/api/3/status/10000",
                    "description": "",
                    "name": "To Do",
                    "id": "10000",
                    "statusCategory": {
                        "self": f"{BASE_URL}/jira/rest/api/3/statuscategory/2",
                        "id": 2, "key": "new", "colorName": "blue-gray", "name": "To Do",
                    },
                },
                "priority": {
                    "self": f"{BASE_URL}/jira/rest/api/3/priority/3",
                    "name": "Medium", "id": "3",
                },
                "assignee": None,
                "reporter": {
                    "self": f"{BASE_URL}/jira/rest/api/3/user?accountId=system",
                    "accountId": "system",
                    "displayName": "System Import",
                    "active": True, "accountType": "atlassian",
                },
                "issuetype": {
                    "self": f"{BASE_URL}/jira/rest/api/3/issuetype/10001",
                    "id": "10001", "name": "Story",
                    "description": "Functionality or a feature expressed as a user goal.",
                    "subtask": False, "hierarchyLevel": 0,
                },
                "project": {
                    "self": f"{BASE_URL}/jira/rest/api/3/project/{JIRA_PROJECT_ID}",
                    "id": JIRA_PROJECT_ID, "key": JIRA_PROJECT_KEY,
                    "name": "WorkFlex Platform", "projectTypeKey": "software",
                },
                "created": ts_str,
                "updated": ts_str,
                "labels": [],
                "components": [],
                "fixVersions": [],
            },
        }

        jira_issues[key] = issue
        jira_issues[issue_id] = issue
        jira_comments[key] = []
        jira_next_ticket_num = max(jira_next_ticket_num, num + 1)


def _seed_hubspot():
    with open(DATA_DIR / "crm_data.json", encoding="utf-8") as f:
        companies = json.load(f)

    for i, c in enumerate(companies):
        cid = str(100001 + i)
        name = c["company_name"]
        domain = (
            name.lower()
            .replace(" ", "")
            .replace(".", "")
            .replace(",", "")
            .replace("&", "and")
            .replace("'", "")
            + ".com"
        )
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc) + timedelta(days=i * 8)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        hubspot_companies[cid] = {
            "id": cid,
            "properties": {
                "name": name,
                "domain": domain,
                "annualrevenue": str(c["annual_recurring_revenue"]),
                "annual_recurring_revenue": str(c["annual_recurring_revenue"]),
                "industry": "COMPUTER_SOFTWARE",
                "lifecyclestage": "customer",
                "numberofemployees": None,
                "city": None,
                "state": None,
                "country": None,
                "createdate": ts_str,
                "hs_lastmodifieddate": ts_str,
                "hs_object_id": cid,
            },
            "createdAt": ts_str,
            "updatedAt": ts_str,
            "archived": False,
        }


def _seed_teams():
    with open(DATA_DIR / "teams_messages.json", encoding="utf-8") as f:
        messages = json.load(f)

    senders = sorted({m["sender"] for m in messages})
    for s in senders:
        teams_users[s] = str(uuid.uuid5(uuid.NAMESPACE_DNS, s))

    base_time = datetime(2026, 3, 17, 8, 30, 0, tzinfo=timezone.utc)

    for i, m in enumerate(messages):
        msg_time = base_time + timedelta(minutes=i * 21)
        msg_id = str(int(msg_time.timestamp() * 1000))
        uid = teams_users[m["sender"]]

        teams_messages[msg_id] = {
            "id": msg_id,
            "replyToId": None,
            "etag": msg_id,
            "messageType": "message",
            "createdDateTime": msg_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "lastModifiedDateTime": msg_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "lastEditedDateTime": None,
            "deletedDateTime": None,
            "subject": None,
            "summary": None,
            "chatId": None,
            "importance": "normal",
            "locale": "en-us",
            "webUrl": (
                f"https://teams.microsoft.com/l/message/"
                f"{TEAMS_CHANNEL_ID}/{msg_id}?groupId={TEAMS_TEAM_ID}"
            ),
            "policyViolation": None,
            "eventDetail": None,
            "from": {
                "application": None,
                "device": None,
                "user": {
                    "@odata.type": "#microsoft.graph.teamworkUserIdentity",
                    "id": uid,
                    "displayName": m["sender"],
                    "userIdentityType": "aadUser",
                    "tenantId": TEAMS_TENANT_ID,
                },
            },
            "body": {"contentType": "text", "content": m["text"]},
            "channelIdentity": {
                "teamId": TEAMS_TEAM_ID,
                "channelId": TEAMS_CHANNEL_ID,
            },
            "attachments": [],
            "mentions": [],
            "reactions": [],
            "messageHistory": [],
        }
        teams_replies[msg_id] = []


_seed_jira()
_seed_hubspot()
_seed_teams()


# ============================================================
# Auth Helpers
# ============================================================

def _require_jira_auth(authorization: Optional[str]) -> str:
    """Jira uses HTTP Basic auth: base64(email:api_token)."""
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Use: Authorization: Basic base64(email:api_key)",
        )
    try:
        decoded = base64.b64decode(authorization[6:]).decode()
        email, api_key = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Malformed Basic auth header.")

    if api_key not in valid_api_keys and api_key not in jira_api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return email


def _require_hubspot_auth(authorization: Optional[str]) -> str:
    """HubSpot uses Bearer token (private-app access token)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "message": "Authentication credentials not found. Expected: Authorization: Bearer <access_token>",
                "category": "INVALID_AUTHENTICATION",
            },
        )
    token = authorization[7:]
    if token not in valid_api_keys and token not in hubspot_api_keys:
        raise HTTPException(
            status_code=401,
            detail={
                "status": "error",
                "message": "The API key provided is invalid.",
                "category": "INVALID_AUTHENTICATION",
            },
        )
    return token


def _require_teams_auth(authorization: Optional[str]) -> dict:
    """MS Graph uses OAuth 2.0 Bearer token obtained via client-credentials flow."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "InvalidAuthenticationToken",
                    "message": "Access token is empty.",
                    "innerError": {
                        "date": datetime.now(timezone.utc).isoformat(),
                        "request-id": str(uuid.uuid4()),
                    },
                }
            },
        )
    token = authorization[7:]
    meta = teams_tokens.get(token)
    if not meta:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "InvalidAuthenticationToken",
                    "message": "Access token has expired or is not yet valid.",
                    "innerError": {
                        "date": datetime.now(timezone.utc).isoformat(),
                        "request-id": str(uuid.uuid4()),
                    },
                }
            },
        )
    return meta


def _require_team_channel(team_id: str, channel_id: str):
    if team_id != TEAMS_TEAM_ID:
        raise HTTPException(404, detail={"error": {"code": "NotFound", "message": f"Team '{team_id}' not found."}})
    if channel_id != TEAMS_CHANNEL_ID:
        raise HTTPException(404, detail={"error": {"code": "NotFound", "message": f"Channel '{channel_id}' not found."}})


# ============================================================
# Auth Endpoints
# ============================================================

@app.post("/auth/teams/token", tags=["Microsoft Teams"],
          summary="Exchange credentials for a Graph API access token")
async def teams_oauth_token(request: Request):
    """
    Mimics `POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token`.

    Send `application/x-www-form-urlencoded` with:
    - `grant_type` = `client_credentials`
    - `client_id` = any string
    - `client_secret` = your API key
    - `scope` = `https://graph.microsoft.com/.default`
    """
    ct = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in ct:
        data = dict(await request.form())
    elif "application/json" in ct:
        data = await request.json()
    else:
        try:
            data = dict(await request.form())
        except Exception:
            raise HTTPException(400, "Expected application/x-www-form-urlencoded or application/json")

    if data.get("grant_type") != "client_credentials":
        raise HTTPException(400, detail={
            "error": "unsupported_grant_type",
            "error_description": "Expected grant_type=client_credentials",
        })

    secret = data.get("client_secret", "")
    if secret not in valid_api_keys and secret not in teams_api_keys:
        raise HTTPException(401, detail={
            "error": "invalid_client",
            "error_description": "Invalid client_secret. Generate one from the Token Dashboard at /dashboard.",
        })

    access_token = f"eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.{secrets.token_hex(32)}"
    teams_tokens[access_token] = {"api_key": secret, "created_at": time.time()}

    return {
        "token_type": "Bearer",
        "expires_in": 3600,
        "ext_expires_in": 3600,
        "access_token": access_token,
    }


# ============================================================
# Per-Service Token Endpoints (for Dashboard UI)
# ============================================================

@app.post("/auth/tokens/jira", include_in_schema=False)
async def create_jira_token(request: Request):
    email = "candidate@workflex.com"
    try:
        body = await request.json()
        email = body.get("email", email)
    except Exception:
        pass
    key = f"jira-token-{secrets.token_hex(16)}"
    jira_api_keys.add(key)
    b64 = base64.b64encode(f"{email}:{key}".encode()).decode()
    data = {
        "service": "jira",
        "token": key,
        "email": email,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_header": f"Authorization: Basic {b64}",
    }
    dashboard_tokens["jira"] = data
    return data


@app.post("/auth/tokens/hubspot", include_in_schema=False)
async def create_hubspot_token():
    key = f"hs-pat-{secrets.token_hex(16)}"
    hubspot_api_keys.add(key)
    data = {
        "service": "hubspot",
        "token": key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auth_header": f"Authorization: Bearer {key}",
    }
    dashboard_tokens["hubspot"] = data
    return data


@app.post("/auth/tokens/teams", include_in_schema=False)
async def create_teams_token():
    key = f"teams-secret-{secrets.token_hex(16)}"
    teams_api_keys.add(key)
    data = {
        "service": "teams",
        "token": key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "token_endpoint": f"{BASE_URL}/auth/teams/token",
    }
    dashboard_tokens["teams"] = data
    return data


@app.get("/auth/tokens", include_in_schema=False)
async def get_tokens():
    """Return all currently active dashboard tokens."""
    return dashboard_tokens


# ============================================================
# Dashboard UI
# ============================================================

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WorkFlex Mock API — Token Dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface-hover: #222632;
    --border: #2a2e3b;
    --text: #e4e6eb;
    --text-dim: #8b8fa3;
    --accent-jira: #2684FF;
    --accent-hubspot: #FF7A59;
    --accent-teams: #7B83EB;
    --green: #34d399;
    --radius: 12px;
    --font: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    --mono: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: var(--font);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0;
  }

  .header {
    border-bottom: 1px solid var(--border);
    padding: 24px 40px;
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .header h1 {
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }

  .header .badge {
    font-size: 11px;
    font-weight: 500;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 8px;
    color: var(--text-dim);
  }

  .header-links {
    margin-left: auto;
    display: flex;
    gap: 8px;
  }

  .header .docs-link {
    font-size: 13px;
    color: var(--text-dim);
    text-decoration: none;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 14px;
    transition: all 0.15s;
  }
  .header .docs-link:hover { background: var(--surface); color: var(--text); }

  .container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 40px 24px;
  }

  .subtitle {
    color: var(--text-dim);
    font-size: 14px;
    margin-bottom: 32px;
    line-height: 1.5;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 20px;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: #3a3e4b; }

  .card-header {
    padding: 20px 24px;
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid var(--border);
  }

  .card-icon {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    font-weight: 700;
    flex-shrink: 0;
  }

  .card.jira .card-icon    { background: color-mix(in srgb, var(--accent-jira) 15%, transparent); color: var(--accent-jira); }
  .card.hubspot .card-icon { background: color-mix(in srgb, var(--accent-hubspot) 15%, transparent); color: var(--accent-hubspot); }
  .card.teams .card-icon   { background: color-mix(in srgb, var(--accent-teams) 15%, transparent); color: var(--accent-teams); }

  .card-title {
    font-size: 15px;
    font-weight: 600;
  }

  .card-auth-type {
    font-size: 12px;
    color: var(--text-dim);
    margin-top: 2px;
  }

  .card-body {
    padding: 20px 24px;
    min-height: 180px;
    display: flex;
    flex-direction: column;
  }

  .generate-btn {
    width: 100%;
    padding: 10px 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface-hover);
    color: var(--text);
    font-family: var(--font);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    margin-top: auto;
  }
  .generate-btn:hover { background: #2d3140; border-color: #444; }

  .card.jira .generate-btn:hover    { border-color: var(--accent-jira); }
  .card.hubspot .generate-btn:hover { border-color: var(--accent-hubspot); }
  .card.teams .generate-btn:hover   { border-color: var(--accent-teams); }

  .token-result {
    display: none;
    flex-direction: column;
    gap: 12px;
    flex: 1;
  }
  .token-result.visible { display: flex; }

  .token-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-dim);
  }

  .token-value {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    font-family: var(--mono);
    font-size: 12px;
    word-break: break-all;
    line-height: 1.5;
    position: relative;
    color: var(--green);
  }

  .token-value .copy-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    color: var(--text-dim);
    cursor: pointer;
    font-family: var(--font);
    transition: all 0.15s;
  }
  .token-value .copy-btn:hover { background: var(--surface-hover); color: var(--text); }

  .auth-header-block {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    font-family: var(--mono);
    font-size: 11px;
    word-break: break-all;
    line-height: 1.6;
    color: var(--text-dim);
    position: relative;
  }
  .auth-header-block .copy-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
    color: var(--text-dim);
    cursor: pointer;
    font-family: var(--font);
    transition: all 0.15s;
  }
  .auth-header-block .copy-btn:hover { background: var(--surface-hover); color: var(--text); }

  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--text-dim);
    display: inline-block;
    margin-right: 6px;
  }
  .status-dot.active { background: var(--green); }

  .status-line {
    font-size: 12px;
    color: var(--text-dim);
    display: flex;
    align-items: center;
  }

  .regen-btn {
    font-size: 12px;
    color: var(--text-dim);
    background: none;
    border: none;
    cursor: pointer;
    text-decoration: underline;
    font-family: var(--font);
    margin-top: 4px;
    padding: 0;
    align-self: flex-end;
  }
  .regen-btn:hover { color: var(--text); }

  .teams-step {
    font-size: 12px;
    color: var(--text-dim);
    line-height: 1.5;
    margin-top: 4px;
  }
  .teams-step code {
    font-family: var(--mono);
    font-size: 11px;
    background: var(--bg);
    padding: 1px 5px;
    border-radius: 4px;
    color: var(--text);
  }
</style>
</head>
<body>

<div class="header">
  <h1>WorkFlex Mock API</h1>
  <span class="badge">Token Dashboard</span>
  <div class="header-links">
    <a href="/docs" class="docs-link" target="_blank">Swagger UI &rarr;</a>
  </div>
</div>

<div class="container">
  <p class="subtitle">
    Generate separate API tokens for each service below. Each token only works with its respective API.
  </p>

  <div class="cards">

    <!-- JIRA -->
    <div class="card jira" id="card-jira">
      <div class="card-header">
        <div class="card-icon">J</div>
        <div>
          <div class="card-title">Jira Cloud</div>
          <div class="card-auth-type">HTTP Basic Authentication</div>
        </div>
      </div>
      <div class="card-body">
        <div class="token-result" id="result-jira">
          <div>
            <div class="status-line"><span class="status-dot active"></span> Token active</div>
          </div>
          <div>
            <div class="token-label">Username (email)</div>
            <div class="token-value" style="color: var(--text);">
              <span id="username-jira-display"></span>
            </div>
          </div>
          <div>
            <div class="token-label">API Token</div>
            <div class="token-value">
              <span id="token-jira"></span>
              <button class="copy-btn" onclick="copyText('token-jira')">Copy</button>
            </div>
          </div>
          <div>
            <div class="token-label">Authorization Header</div>
            <div class="auth-header-block">
              <span id="header-jira"></span>
              <button class="copy-btn" onclick="copyText('header-jira')">Copy</button>
            </div>
          </div>
          <button class="regen-btn" onclick="resetJira()">Regenerate</button>
        </div>
        <div id="jira-form">
          <div style="margin-bottom: 12px;">
            <div class="token-label" style="margin-bottom: 6px;">Username (email)</div>
            <input type="email" id="jira-email" placeholder="candidate@workflex.com" value="candidate@workflex.com"
              style="width:100%; padding:9px 12px; border-radius:8px; border:1px solid var(--border); background:var(--bg); color:var(--text); font-family:var(--font); font-size:13px; outline:none;"
              onfocus="this.style.borderColor='var(--accent-jira)'" onblur="this.style.borderColor='var(--border)'" />
            <div style="font-size:11px; color:var(--text-dim); margin-top:4px;">Jira Basic auth requires base64(email:token)</div>
          </div>
          <button class="generate-btn" id="btn-jira" onclick="generateToken('jira')">Generate Jira Token</button>
        </div>
      </div>
    </div>

    <!-- HUBSPOT -->
    <div class="card hubspot" id="card-hubspot">
      <div class="card-header">
        <div class="card-icon">H</div>
        <div>
          <div class="card-title">HubSpot CRM</div>
          <div class="card-auth-type">Bearer Token (Private App)</div>
        </div>
      </div>
      <div class="card-body">
        <div class="token-result" id="result-hubspot">
          <div>
            <div class="status-line"><span class="status-dot active"></span> Token active</div>
          </div>
          <div>
            <div class="token-label">Access Token</div>
            <div class="token-value">
              <span id="token-hubspot"></span>
              <button class="copy-btn" onclick="copyText('token-hubspot')">Copy</button>
            </div>
          </div>
          <div>
            <div class="token-label">Authorization Header</div>
            <div class="auth-header-block">
              <span id="header-hubspot"></span>
              <button class="copy-btn" onclick="copyText('header-hubspot')">Copy</button>
            </div>
          </div>
          <button class="regen-btn" onclick="generateToken('hubspot')">Regenerate</button>
        </div>
        <button class="generate-btn" id="btn-hubspot" onclick="generateToken('hubspot')">Generate HubSpot Token</button>
      </div>
    </div>

    <!-- TEAMS -->
    <div class="card teams" id="card-teams">
      <div class="card-header">
        <div class="card-icon">T</div>
        <div>
          <div class="card-title">Microsoft Teams</div>
          <div class="card-auth-type">OAuth 2.0 Client Credentials</div>
        </div>
      </div>
      <div class="card-body">
        <div class="token-result" id="result-teams">
          <div>
            <div class="status-line"><span class="status-dot active"></span> Secret active</div>
          </div>
          <div>
            <div class="token-label">Client Secret</div>
            <div class="token-value">
              <span id="token-teams"></span>
              <button class="copy-btn" onclick="copyText('token-teams')">Copy</button>
            </div>
          </div>
          <div>
            <div class="token-label">Token Endpoint</div>
            <div class="auth-header-block">
              <span id="header-teams"></span>
              <button class="copy-btn" onclick="copyText('header-teams')">Copy</button>
            </div>
          </div>
          <div class="teams-step">
            Exchange via <code>POST /auth/teams/token</code> with
            <code>grant_type=client_credentials</code> to get a Bearer access token.
          </div>
          <button class="regen-btn" onclick="generateToken('teams')">Regenerate</button>
        </div>
        <button class="generate-btn" id="btn-teams" onclick="generateToken('teams')">Generate Teams Secret</button>
      </div>
    </div>

  </div>
</div>

<script>
function showToken(service, data) {
  const result = document.getElementById('result-' + service);
  document.getElementById('token-' + service).textContent = data.token;

  if (service === 'jira') {
    document.getElementById('username-jira-display').textContent = data.email;
    document.getElementById('header-jira').textContent = data.auth_header;
    document.getElementById('jira-form').style.display = 'none';
  } else if (service === 'hubspot') {
    document.getElementById('header-hubspot').textContent = data.auth_header;
    document.getElementById('btn-hubspot').style.display = 'none';
  } else if (service === 'teams') {
    document.getElementById('header-teams').textContent = data.token_endpoint;
    document.getElementById('btn-teams').style.display = 'none';
  }

  result.classList.add('visible');
}

async function generateToken(service) {
  const btn = document.getElementById('btn-' + service);
  const origText = btn.textContent;
  btn.textContent = 'Generating...';
  btn.disabled = true;

  try {
    const fetchOpts = { method: 'POST' };
    if (service === 'jira') {
      const email = document.getElementById('jira-email').value || 'candidate@workflex.com';
      fetchOpts.headers = { 'Content-Type': 'application/json' };
      fetchOpts.body = JSON.stringify({ email });
    }

    const res = await fetch('/auth/tokens/' + service, fetchOpts);
    const data = await res.json();
    showToken(service, data);
  } catch {
    btn.textContent = origText;
    btn.disabled = false;
  }
}

function resetJira() {
  document.getElementById('result-jira').classList.remove('visible');
  document.getElementById('jira-form').style.display = '';
  const btn = document.getElementById('btn-jira');
  btn.style.display = '';
  btn.textContent = 'Generate Jira Token';
  btn.disabled = false;
}

async function copyText(elementId) {
  const text = document.getElementById(elementId).textContent;
  try {
    await navigator.clipboard.writeText(text);
    const btn = document.getElementById(elementId).parentElement.querySelector('.copy-btn');
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1200);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

(async function restoreOnLoad() {
  try {
    const res = await fetch('/auth/tokens');
    const saved = await res.json();
    for (const service of ['jira', 'hubspot', 'teams']) {
      if (saved[service]) showToken(service, saved[service]);
    }
  } catch {}
})();
</script>
</body>
</html>
"""


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    """Token management dashboard UI."""
    return DASHBOARD_HTML


# ============================================================
# Jira Cloud REST API v3
# ============================================================

@app.get("/jira/rest/api/3/search", tags=["Jira"],
         summary="Search issues (JQL)")
async def jira_search_issues(
    jql: Optional[str] = None,
    startAt: int = 0,
    maxResults: int = 50,
    fields: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _require_jira_auth(authorization)

    seen, all_issues = set(), []
    for issue in jira_issues.values():
        if issue["key"] not in seen:
            seen.add(issue["key"])
            all_issues.append(issue)
    all_issues.sort(key=lambda i: i["key"])

    total = len(all_issues)
    page = all_issues[startAt : startAt + maxResults]

    return {
        "expand": "schema,names",
        "startAt": startAt,
        "maxResults": maxResults,
        "total": total,
        "issues": page,
    }


@app.get("/jira/rest/api/3/issue/{issue_id_or_key}", tags=["Jira"],
         summary="Get issue by key or ID")
async def jira_get_issue(
    issue_id_or_key: str,
    authorization: Optional[str] = Header(None),
):
    _require_jira_auth(authorization)
    issue = jira_issues.get(issue_id_or_key)
    if not issue:
        raise HTTPException(404, "Issue does not exist or you do not have permission to see it.")

    result = json.loads(json.dumps(issue))
    comments = jira_comments.get(issue["key"], [])
    result["fields"]["comment"] = {
        "comments": comments,
        "maxResults": len(comments),
        "total": len(comments),
        "startAt": 0,
    }
    return result


@app.post("/jira/rest/api/3/issue", tags=["Jira"], status_code=201,
          summary="Create a new issue")
async def jira_create_issue(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    _require_jira_auth(authorization)
    body = await request.json()
    fields = body.get("fields", {})

    summary = fields.get("summary")
    if not summary:
        raise HTTPException(400, "Field 'summary' is required.")

    global jira_next_ticket_num
    num = jira_next_ticket_num
    jira_next_ticket_num += 1
    key = f"{fields.get('project', {}).get('key', JIRA_PROJECT_KEY)}-{num}"
    issue_id = str(10000 + num)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    desc = fields.get("description", _to_adf("No description provided."))
    if isinstance(desc, str):
        desc = _to_adf(desc)

    issue = {
        "expand": "operations,versionedRepresentations,editmeta,changelog,renderedFields",
        "id": issue_id,
        "self": f"{BASE_URL}/jira/rest/api/3/issue/{issue_id}",
        "key": key,
        "fields": {
            "summary": summary,
            "description": desc,
            "status": {
                "self": f"{BASE_URL}/jira/rest/api/3/status/10000",
                "description": "", "name": "To Do", "id": "10000",
                "statusCategory": {"id": 2, "key": "new", "colorName": "blue-gray", "name": "To Do"},
            },
            "priority": fields.get("priority", {"name": "Medium", "id": "3"}),
            "assignee": fields.get("assignee"),
            "reporter": {
                "accountId": "bridge-agent",
                "displayName": "Bridge Agent",
                "active": True, "accountType": "atlassian",
            },
            "issuetype": {
                "id": "10001",
                "name": fields.get("issuetype", {}).get("name", "Story"),
                "subtask": False, "hierarchyLevel": 0,
            },
            "project": {
                "id": JIRA_PROJECT_ID,
                "key": fields.get("project", {}).get("key", JIRA_PROJECT_KEY),
                "name": "WorkFlex Platform", "projectTypeKey": "software",
            },
            "created": now,
            "updated": now,
            "labels": fields.get("labels", []),
            "components": fields.get("components", []),
            "fixVersions": [],
        },
    }

    jira_issues[key] = issue
    jira_issues[issue_id] = issue
    jira_comments[key] = []

    return {"id": issue_id, "key": key, "self": f"{BASE_URL}/jira/rest/api/3/issue/{issue_id}"}


@app.get("/jira/rest/api/3/issue/{issue_id_or_key}/comment", tags=["Jira"],
         summary="Get comments for an issue")
async def jira_get_comments(
    issue_id_or_key: str,
    startAt: int = 0,
    maxResults: int = 50,
    authorization: Optional[str] = Header(None),
):
    _require_jira_auth(authorization)
    issue = jira_issues.get(issue_id_or_key)
    if not issue:
        raise HTTPException(404, "Issue does not exist or you do not have permission to see it.")

    comments = jira_comments.get(issue["key"], [])
    page = comments[startAt : startAt + maxResults]
    return {
        "self": f"{BASE_URL}/jira/rest/api/3/issue/{issue['id']}/comment",
        "maxResults": maxResults,
        "startAt": startAt,
        "total": len(comments),
        "comments": page,
    }


@app.post("/jira/rest/api/3/issue/{issue_id_or_key}/comment", tags=["Jira"],
          status_code=201, summary="Add a comment to an issue")
async def jira_add_comment(
    issue_id_or_key: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    email = _require_jira_auth(authorization)
    issue = jira_issues.get(issue_id_or_key)
    if not issue:
        raise HTTPException(404, "Issue does not exist or you do not have permission to see it.")

    body = await request.json()
    comment_body = body.get("body", {})
    if isinstance(comment_body, str):
        comment_body = _to_adf(comment_body)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    cid = str(int(time.time() * 1000))

    comment = {
        "self": f"{BASE_URL}/jira/rest/api/3/issue/{issue['id']}/comment/{cid}",
        "id": cid,
        "author": {
            "accountId": "bridge-agent",
            "emailAddress": email,
            "displayName": "Bridge Agent",
            "active": True, "accountType": "atlassian",
        },
        "body": comment_body,
        "updateAuthor": {
            "accountId": "bridge-agent",
            "displayName": "Bridge Agent",
            "active": True, "accountType": "atlassian",
        },
        "created": now,
        "updated": now,
        "jsdPublic": True,
    }

    jira_comments[issue["key"]].append(comment)
    issue["fields"]["updated"] = now
    return comment


# ============================================================
# HubSpot CRM API v3
# ============================================================

def _hs_filter_props(company: dict, requested: Optional[list] = None) -> dict:
    result = {
        "id": company["id"],
        "createdAt": company["createdAt"],
        "updatedAt": company["updatedAt"],
        "archived": company["archived"],
    }
    if requested:
        props = {
            "createdate": company["properties"]["createdate"],
            "hs_lastmodifieddate": company["properties"]["hs_lastmodifieddate"],
            "hs_object_id": company["properties"]["hs_object_id"],
        }
        for p in requested:
            if p in company["properties"]:
                props[p] = company["properties"][p]
        result["properties"] = props
    else:
        result["properties"] = company["properties"]
    return result


@app.get("/hubspot/crm/v3/objects/companies", tags=["HubSpot CRM"],
         summary="List companies")
async def hubspot_list_companies(
    limit: int = Query(10, le=100),
    after: Optional[str] = None,
    properties: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _require_hubspot_auth(authorization)

    req_props = [p.strip() for p in properties.split(",")] if properties else None
    all_cos = sorted(hubspot_companies.values(), key=lambda c: c["id"])

    start = 0
    if after:
        for i, c in enumerate(all_cos):
            if c["id"] == after:
                start = i + 1
                break

    page = all_cos[start : start + limit]
    resp: dict = {"results": [_hs_filter_props(c, req_props) for c in page]}

    if start + limit < len(all_cos):
        resp["paging"] = {
            "next": {
                "after": page[-1]["id"],
                "link": f"{BASE_URL}/hubspot/crm/v3/objects/companies?limit={limit}&after={page[-1]['id']}",
            }
        }
    return resp


@app.get("/hubspot/crm/v3/objects/companies/{company_id}", tags=["HubSpot CRM"],
         summary="Get a single company")
async def hubspot_get_company(
    company_id: str,
    properties: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    _require_hubspot_auth(authorization)
    co = hubspot_companies.get(company_id)
    if not co:
        raise HTTPException(404, detail={
            "status": "error",
            "message": f"Object not found. objectType=COMPANY, objectId={company_id}",
            "correlationId": str(uuid.uuid4()),
            "category": "OBJECT_NOT_FOUND",
        })
    req_props = [p.strip() for p in properties.split(",")] if properties else None
    return _hs_filter_props(co, req_props)


@app.post("/hubspot/crm/v3/objects/companies/search", tags=["HubSpot CRM"],
          summary="Search companies")
async def hubspot_search_companies(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    _require_hubspot_auth(authorization)
    body = await request.json()

    query = body.get("query", "")
    filter_groups = body.get("filterGroups", [])
    req_props = body.get("properties")
    limit = min(body.get("limit", 10), 100)
    after = int(body.get("after", 0))

    results = list(hubspot_companies.values())

    # Full-text search
    if query:
        q = query.lower()
        results = [
            c for c in results
            if q in c["properties"]["name"].lower()
            or (c["properties"].get("domain") and q in c["properties"]["domain"].lower())
        ]

    # Filter groups (OR between groups, AND within)
    if filter_groups:
        filtered = []
        for co in results:
            for grp in filter_groups:
                match = True
                for f in grp.get("filters", []):
                    pv = str(co["properties"].get(f["propertyName"], "") or "")
                    val = str(f.get("value", ""))
                    op = f.get("operator", "EQ")
                    if op == "EQ" and pv.lower() != val.lower():
                        match = False
                    elif op == "CONTAINS_TOKEN" and val.lower() not in pv.lower():
                        match = False
                    elif op in ("GT", "GTE", "LT", "LTE"):
                        try:
                            pf, vf = float(pv), float(val)
                            if op == "GT" and pf <= vf: match = False
                            elif op == "GTE" and pf < vf: match = False
                            elif op == "LT" and pf >= vf: match = False
                            elif op == "LTE" and pf > vf: match = False
                        except ValueError:
                            match = False
                    if not match:
                        break
                if match:
                    filtered.append(co)
                    break
        results = filtered

    total = len(results)
    page = results[after : after + limit]

    resp: dict = {
        "total": total,
        "results": [_hs_filter_props(c, req_props) for c in page],
    }
    if after + limit < total:
        resp["paging"] = {"next": {"after": str(after + limit)}}
    return resp


# ============================================================
# Microsoft Graph API — Teams
# ============================================================

@app.get("/graph/v1.0/teams", tags=["Microsoft Teams"],
         summary="List joined teams (discover team ID)")
async def teams_list_teams(authorization: Optional[str] = Header(None)):
    _require_teams_auth(authorization)
    return {
        "@odata.context": f"{BASE_URL}/graph/v1.0/$metadata#teams",
        "@odata.count": 1,
        "value": [{
            "id": TEAMS_TEAM_ID,
            "displayName": "WorkFlex Product Team",
            "description": "Product and engineering team",
            "isArchived": False,
        }],
    }


@app.get("/graph/v1.0/teams/{team_id}/channels", tags=["Microsoft Teams"],
         summary="List channels (discover channel ID)")
async def teams_list_channels(
    team_id: str,
    authorization: Optional[str] = Header(None),
):
    _require_teams_auth(authorization)
    if team_id != TEAMS_TEAM_ID:
        raise HTTPException(404, detail={"error": {"code": "NotFound", "message": "Team not found."}})

    return {
        "@odata.context": f"{BASE_URL}/graph/v1.0/$metadata#teams('{team_id}')/channels",
        "@odata.count": 1,
        "value": [{
            "id": TEAMS_CHANNEL_ID,
            "displayName": "#feature-requests",
            "description": "Channel for customer feature requests and feedback",
            "membershipType": "standard",
        }],
    }


@app.get("/graph/v1.0/teams/{team_id}/channels/{channel_id}/messages",
         tags=["Microsoft Teams"], summary="List channel messages")
async def teams_list_messages(
    team_id: str,
    channel_id: str,
    top: Optional[int] = Query(None, alias="$top"),
    skiptoken: Optional[str] = Query(None, alias="$skiptoken"),
    authorization: Optional[str] = Header(None),
):
    """
    Returns messages in reverse chronological order (newest first).

    Pagination: use `$top` (max 50) and follow `@odata.nextLink`.
    """
    _require_teams_auth(authorization)
    _require_team_channel(team_id, channel_id)

    page_size = min(top or 20, 50)
    all_msgs = sorted(teams_messages.values(), key=lambda m: m["createdDateTime"], reverse=True)

    start = 0
    if skiptoken:
        for i, m in enumerate(all_msgs):
            if m["id"] == skiptoken:
                start = i + 1
                break

    page = all_msgs[start : start + page_size]

    resp: dict = {
        "@odata.context": (
            f"{BASE_URL}/graph/v1.0/$metadata#teams('{team_id}')"
            f"/channels('{channel_id}')/messages"
        ),
        "@odata.count": len(all_msgs),
        "value": page,
    }

    if start + page_size < len(all_msgs):
        resp["@odata.nextLink"] = (
            f"{BASE_URL}/graph/v1.0/teams/{team_id}/channels/{channel_id}"
            f"/messages?$top={page_size}&$skiptoken={page[-1]['id']}"
        )

    return resp


@app.get("/graph/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}",
         tags=["Microsoft Teams"], summary="Get a single message")
async def teams_get_message(
    team_id: str,
    channel_id: str,
    message_id: str,
    authorization: Optional[str] = Header(None),
):
    _require_teams_auth(authorization)
    _require_team_channel(team_id, channel_id)

    msg = teams_messages.get(message_id)
    if not msg:
        raise HTTPException(404, detail={"error": {"code": "NotFound", "message": "Message not found."}})
    return msg


@app.post("/graph/v1.0/teams/{team_id}/channels/{channel_id}/messages",
          tags=["Microsoft Teams"], status_code=201,
          summary="Send a message to a channel")
async def teams_send_message(
    team_id: str,
    channel_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    _require_teams_auth(authorization)
    _require_team_channel(team_id, channel_id)

    body = await request.json()
    msg_body = body.get("body", {})
    if isinstance(msg_body, str):
        msg_body = {"contentType": "text", "content": msg_body}

    now = datetime.now(timezone.utc)
    msg_id = str(int(now.timestamp() * 1000))

    message = {
        "id": msg_id,
        "replyToId": None,
        "etag": msg_id,
        "messageType": "message",
        "createdDateTime": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "lastModifiedDateTime": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "lastEditedDateTime": None,
        "deletedDateTime": None,
        "subject": body.get("subject"),
        "summary": None,
        "chatId": None,
        "importance": body.get("importance", "normal"),
        "locale": "en-us",
        "webUrl": f"https://teams.microsoft.com/l/message/{channel_id}/{msg_id}",
        "policyViolation": None,
        "eventDetail": None,
        "from": {
            "application": {
                "id": "bridge-agent-app",
                "displayName": "WorkFlex Bridge Agent",
                "applicationIdentityType": "bot",
            },
            "device": None,
            "user": None,
        },
        "body": msg_body,
        "channelIdentity": {"teamId": team_id, "channelId": channel_id},
        "attachments": body.get("attachments", []),
        "mentions": body.get("mentions", []),
        "reactions": [],
        "messageHistory": [],
    }

    teams_messages[msg_id] = message
    teams_replies[msg_id] = []
    return message


@app.get("/graph/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies",
         tags=["Microsoft Teams"], summary="Get replies to a message")
async def teams_get_replies(
    team_id: str,
    channel_id: str,
    message_id: str,
    top: Optional[int] = Query(None, alias="$top"),
    authorization: Optional[str] = Header(None),
):
    _require_teams_auth(authorization)
    _require_team_channel(team_id, channel_id)

    if message_id not in teams_messages:
        raise HTTPException(404, detail={"error": {"code": "NotFound", "message": "Message not found."}})

    replies = teams_replies.get(message_id, [])
    if top:
        replies = replies[:top]

    return {
        "@odata.context": (
            f"{BASE_URL}/graph/v1.0/$metadata#teams('{team_id}')"
            f"/channels('{channel_id}')/messages('{message_id}')/replies"
        ),
        "@odata.count": len(replies),
        "value": replies,
    }


@app.post("/graph/v1.0/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies",
          tags=["Microsoft Teams"], status_code=201,
          summary="Reply to a message")
async def teams_reply_to_message(
    team_id: str,
    channel_id: str,
    message_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    _require_teams_auth(authorization)
    _require_team_channel(team_id, channel_id)

    if message_id not in teams_messages:
        raise HTTPException(404, detail={"error": {"code": "NotFound", "message": "Message not found."}})

    body = await request.json()
    msg_body = body.get("body", {})
    if isinstance(msg_body, str):
        msg_body = {"contentType": "text", "content": msg_body}

    now = datetime.now(timezone.utc)
    reply_id = str(int(now.timestamp() * 1000))

    reply = {
        "id": reply_id,
        "replyToId": message_id,
        "etag": reply_id,
        "messageType": "message",
        "createdDateTime": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "lastModifiedDateTime": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "lastEditedDateTime": None,
        "deletedDateTime": None,
        "subject": None,
        "summary": None,
        "chatId": None,
        "importance": body.get("importance", "normal"),
        "locale": "en-us",
        "webUrl": (
            f"https://teams.microsoft.com/l/message/{channel_id}/{reply_id}"
            f"?parentMessageId={message_id}"
        ),
        "policyViolation": None,
        "eventDetail": None,
        "from": {
            "application": {
                "id": "bridge-agent-app",
                "displayName": "WorkFlex Bridge Agent",
                "applicationIdentityType": "bot",
            },
            "device": None,
            "user": None,
        },
        "body": msg_body,
        "channelIdentity": {"teamId": team_id, "channelId": channel_id},
        "attachments": body.get("attachments", []),
        "mentions": body.get("mentions", []),
        "reactions": [],
        "messageHistory": [],
    }

    teams_replies[message_id].append(reply)
    return reply


# ============================================================
# Root
# ============================================================

@app.get("/", tags=["Info"], summary="API overview")
async def root():
    return {
        "name": "WorkFlex Mock API Server",
        "version": "1.0.0",
        "getting_started": "Open the Token Dashboard at /dashboard to generate API tokens, then see /docs for full endpoint reference.",
        "services": {
            "jira": {
                "base_path": "/jira/rest/api/3",
                "auth": "Basic base64(email:api_key)",
                "endpoints": [
                    "GET  /jira/rest/api/3/search",
                    "GET  /jira/rest/api/3/issue/{key}",
                    "POST /jira/rest/api/3/issue",
                    "GET  /jira/rest/api/3/issue/{key}/comment",
                    "POST /jira/rest/api/3/issue/{key}/comment",
                ],
            },
            "hubspot": {
                "base_path": "/hubspot/crm/v3",
                "auth": "Bearer <api_key>",
                "endpoints": [
                    "GET  /hubspot/crm/v3/objects/companies",
                    "GET  /hubspot/crm/v3/objects/companies/{id}",
                    "POST /hubspot/crm/v3/objects/companies/search",
                ],
            },
            "teams": {
                "base_path": "/graph/v1.0",
                "auth": "Bearer <access_token> via POST /auth/teams/token",
                "endpoints": [
                    "GET  /graph/v1.0/teams",
                    "GET  /graph/v1.0/teams/{id}/channels",
                    "GET  /graph/v1.0/teams/{id}/channels/{id}/messages",
                    "GET  /graph/v1.0/teams/{id}/channels/{id}/messages/{id}",
                    "POST /graph/v1.0/teams/{id}/channels/{id}/messages",
                    "GET  /graph/v1.0/teams/{id}/channels/{id}/messages/{id}/replies",
                    "POST /graph/v1.0/teams/{id}/channels/{id}/messages/{id}/replies",
                ],
            },
        },
        "docs_url": f"{BASE_URL}/docs",
        "dashboard_url": f"{BASE_URL}/dashboard",
    }


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  WorkFlex Mock API Server")
    print("  Docs:  http://localhost:8080/docs")
    print("  Start: GET  http://localhost:8080/auth/api-key")
    print("=" * 60)
    uvicorn.run("mock_server:app", host="0.0.0.0", port=8080, reload=True)
