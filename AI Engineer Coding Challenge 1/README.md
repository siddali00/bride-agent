# WorkFlex Bridge Agent — Coding Challenge

## Getting Started

### Start the mock server

```bash
docker compose up --build
```

The server will be available at **http://localhost:8080**.

### Create API tokens

Open the **Token Dashboard** at http://localhost:8080/dashboard and generate a separate API key for each of the three systems:

- **Jira** (requires a username/email)
- **HubSpot**
- **Microsoft Teams**

### API documentation

The **Swagger UI** with full endpoint documentation for all three mocks (Jira, HubSpot, and Teams) is linked directly from the dashboard, or available at http://localhost:8080/docs.
