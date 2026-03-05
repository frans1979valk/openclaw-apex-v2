FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn requests

COPY app/ /app/app/
COPY static/ /app/static/

RUN mkdir -p /var/command_center

ENV PYTHONUNBUFFERED=1

EXPOSE 4000

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "4000"]
