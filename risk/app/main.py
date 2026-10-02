from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from .analyzer import RiskAnalyzer
from .explainer import RiskExplainer


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"level": record.levelname.lower(), "service": "risk-service",
                           "event": record.getMessage()})


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
log = logging.getLogger("apex.risk")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.propagate = False


class MarketEvent(BaseModel):
    event_type: str
    account_id: int = Field(gt=0)
    symbol: str
    quantity: int = Field(ge=0)
    side: Optional[str] = None
    trades: int = 0
    cancelled: bool = False


RISK_EVENTS = Counter("apex_risk_events_total", "Risk alerts", ["category", "severity"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(os.getenv(
        "DATABASE_URL", "postgresql://apex:apex_local_only@localhost:5432/apex"
    ), min_size=1, max_size=5)
    app.state.analyzer = RiskAnalyzer(
        int(os.getenv("RISK_WINDOW_SECONDS", "60")),
        int(os.getenv("RISK_ORDER_RATE_THRESHOLD", "30")),
        float(os.getenv("RISK_CANCEL_RATIO_THRESHOLD", "0.8")),
    )
    app.state.explainer = RiskExplainer()
    log.info("service_started")
    yield
    await app.state.pool.close()
    log.info("service_stopped")


app = FastAPI(title="APEX Risk Service", version="1.0.0", lifespan=lifespan)


@app.post("/events")
async def events(event: MarketEvent, request: Request):
    alerts = request.app.state.analyzer.analyze(event.model_dump())
    saved = []
    async with request.app.state.pool.acquire() as conn:
        for alert in alerts:
            alert["explanation"] = await request.app.state.explainer.explain(alert)
            row = await conn.fetchrow(
                """INSERT INTO risk_events(account_id,category,severity,metrics,explanation,created_at)
                   VALUES($1,$2,$3,$4::jsonb,$5,$6) RETURNING *""",
                alert["account_id"], alert["category"], alert["severity"],
                json.dumps(alert["metrics"]), alert["explanation"],
                datetime.fromisoformat(alert["created_at"]),
            )
            value = dict(row)
            value["created_at"] = value["created_at"].isoformat()
            value["metrics"] = json.loads(value["metrics"]) if isinstance(value["metrics"], str) else dict(value["metrics"])
            saved.append(value)
            RISK_EVENTS.labels(alert["category"], alert["severity"]).inc()
            log.info(f"risk_event account={alert['account_id']} category={alert['category']} severity={alert['severity']}")
    return {"risk_events": saved}


@app.get("/health")
async def health(request: Request):
    try:
        async with request.app.state.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "model": "rolling-statistical-v1", "llm_enabled": bool(os.getenv("LLM_API_KEY"))}
    except Exception:
        return {"status": "unhealthy"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
