from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str
    llm_model: str = "anthropic/claude-sonnet-4.6"

    mock_base_url: str = "http://localhost:8080"

    jira_email: str
    jira_token: str
    hubspot_token: str
    teams_client_secret: str

    teams_team_id: str = "a1b2c3d4-e5f6-7890-abcd-ef0123456789"
    teams_channel_id: str = "19:feature-requests@thread.tacv2"
    jira_project_key: str = "JIRA"


settings = Settings()
