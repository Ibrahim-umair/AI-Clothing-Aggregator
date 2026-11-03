FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 4000

# Production: several worker processes so one busy request (or one stuck
# OpenAI call) never holds up the rest, and no --reload (it watches files
# and restarts mid-deploy). WEB_WORKERS sets the count; 2 suits a 2-CPU
# server. Local development gets --reload from db/docker-compose.override.yml.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 4000 --workers ${WEB_WORKERS:-2}"]
