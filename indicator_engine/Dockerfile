# Gebruik apex_engine als base — TA-Lib is daar al geïnstalleerd
FROM openclaw_trading_platform_blofin_demo_v2-apex_engine:latest AS talib_base

FROM python:3.12-slim
WORKDIR /app

# Kopieer TA-Lib shared library vanuit apex_engine
COPY --from=talib_base /usr/lib/libta_lib* /usr/lib/
COPY --from=talib_base /usr/include/ta-lib /usr/include/ta-lib

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY db_compat.py .
COPY universe_manager.py .

EXPOSE 8099

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8099"]
