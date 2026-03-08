FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN wget -q https://github.com/ta-lib/ta-lib/releases/download/v0.4.0/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && ./configure --prefix=/usr && make -j"$(nproc)" && make install && \
    cd / && rm -rf ta-lib ta-lib-0.4.0-src.tar.gz
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
COPY app/db_compat.py /app/db_compat.py
COPY app/testbot.py /app/testbot.py
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080"]
