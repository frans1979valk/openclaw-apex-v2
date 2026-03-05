FROM python:3.12-slim

WORKDIR /workspace

# Dependencies
COPY skills/market_oracle/tools/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Wrapper
COPY market_oracle_sandbox/main.py /workspace/main.py

ENV PYTHONUNBUFFERED=1

EXPOSE 8095

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8095"]
