"""Set required env vars before `app.config.settings` is instantiated at import."""
import os

_defaults = {
    "OPENROUTER_API_KEY": "test-key",
    "JIRA_EMAIL": "test@example.com",
    "JIRA_TOKEN": "jira-token-test",
    "HUBSPOT_TOKEN": "hs-pat-test",
    "TEAMS_CLIENT_SECRET": "teams-secret-test",
    "MOCK_BASE_URL": "http://mock",
}
for k, v in _defaults.items():
    os.environ.setdefault(k, v)
