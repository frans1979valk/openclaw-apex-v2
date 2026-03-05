FROM python:3.12-slim

WORKDIR /workspace

RUN pip install --no-cache-dir fastapi uvicorn requests

# Tool scripts (copied from project root context)
COPY openclaw_tools/scripts/ /workspace/tools/

# Agent prompts
COPY openclaw_tools/prompts/ /workspace/prompts/

# Runtime main
COPY openclaw_runtime/main.py /workspace/main.py

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
