"""
Market Oracle Sandbox — FastAPI wrapper.

Draait in een geïsoleerde container zonder exchange/AI keys.
Alleen publieke RSS feeds en Yahoo Finance.
"""

import sys
sys.path.insert(0, "/workspace/tools")

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from oracle import analyze_event, analyze_url, full_scan

app = FastAPI(title="Market Oracle Sandbox", version="1.0.0")


class EventRequest(BaseModel):
    event: str
    focus: str = "btc,eth,gold"


class UrlRequest(BaseModel):
    url: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "market_oracle_sandbox"}


@app.post("/run_event")
def run_event(req: EventRequest):
    return analyze_event(req.event, req.focus)


@app.post("/run_url")
def run_url(req: UrlRequest):
    return analyze_url(req.url)


@app.get("/scan")
def scan():
    return full_scan()
