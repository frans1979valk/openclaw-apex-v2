FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir requests
RUN mkdir -p /app/telegram
COPY common.py /app/telegram/common.py
COPY __init__.py /app/telegram/__init__.py
COPY discuss_bot/bot.py /app/bot.py
CMD ["python", "bot.py"]
