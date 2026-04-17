FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mock_server.py .
COPY jira_backlog.json .
COPY crm_data.json .
COPY teams_messages.json .

EXPOSE 8080

CMD ["uvicorn", "mock_server:app", "--host", "0.0.0.0", "--port", "8080"]
