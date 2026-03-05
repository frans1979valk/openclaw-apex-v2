FROM python:3.12-slim
WORKDIR /workspace
RUN pip install --no-cache-dir requests openai
COPY bot.py /workspace/bot.py
CMD ["python", "bot.py"]
