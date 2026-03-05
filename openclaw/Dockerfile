FROM python:3.12-slim
WORKDIR /workspace
RUN pip install --no-cache-dir requests openai anthropic
COPY bot.py /workspace/bot.py
COPY clawbot.py /workspace/clawbot.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
