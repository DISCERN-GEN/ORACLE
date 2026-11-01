from __future__ import annotations

import asyncio
import re
import secrets
from pathlib import Path
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .agent import OracleResearchAgent
from .domain import Forecast, OrderIntent, PaperAccount, Side
from .event_intelligence import InformationSource, RSSIngestor, RELIABILITY_TIERS
from .forecasting import BetaPrior, EvidenceItem, create_forecast
from .opportunity import OutcomeLeg, evaluate_complete_set, evaluate_directional
from .portfolio import mean_variance_kelly_approx
from .paper_broker import PaperBroker
from .polymarket import PolymarketClient
from .risk import RiskEngine
from .sessions import PaperSession, SessionState
from .settings import settings
from .store import Store
from .wallet_discovery import discover_wallets, ingest_wallet_activity_history, ingest_wallet_trade_history
from .wallet_intelligence import WalletTrade, reconstruct_wallet
from .wallet_scoring import score_wallet


bearer = HTTPBearer(auto_error=False)
store = Store(settings.database_url)
client = PolymarketClient()
agent = OracleResearchAgent(client, store)
risk_engine = RiskEngine()
paper_broker = PaperBroker()
rss_ingestor = RSSIngestor()
paper_account = PaperAccount.create(settings.paper_initial_bankroll)
active_session: PaperSession | None = None
agent_task: asyncio.Task[None] | None = None
# Deliberately hard-locked until every documented full-system acceptance gate passes.
AUTONOMOUS_ACCEPTANCE_TEST_READY = False


async def require_owner(credentials: HTTPAuthorizationCredentials | None = Security(bearer)) -> None:
    if not credentials or not secrets.compare_digest(credentials.credentials, settings.api_token):
        raise HTTPException(status_code=401, detail="Owner authentication required")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.api_token == "change-this-long-random-token" or len(settings.api_token) < 32:
        raise RuntimeError("Set ORACLE_API_TOKEN to a unique secret of at least 32 characters")
    await store.connect()
    await store.require_schema()
    migration_path = Path(__file__).resolve().parent.parent / "sql" / "002_wallet_intelligence.sql"
    await store.apply_migration_file(migration_path)
    await store.require_schema("002_wallet_intelligence")
    activity_migration_path = Path(__file__).resolve().parent.parent / "sql" / "003_wallet_activity.sql"
    await store.apply_migration_file(activity_migration_path)
    await store.require_schema("003_wallet_activity")
    book_capture_migration_path = Path(__file__).resolve().parent.parent / "sql" / "004_orderbook_capture.sql"
    await store.apply_migration_file(book_capture_migration_path)
    await store.require_schema("004_orderbook_capture")
    await store.fail_interrupted_sessions()
    yield
    await store.close()
    await client.close()
    await rss_ingestor.close()


app = FastAPI(title="ORACLE Private Platform", version="0.6.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"],
)


class StartPaperRequest(BaseModel):
    hours: int = Field(default=settings.paper_session_hours, ge=1, le=24)
    bankroll: Decimal | None = Field(default=None, gt=0)


class StopRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)




class RSSIngestRequest(BaseModel):
    source_id: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=2, max_length=200)
    feed_url: str = Field(min_length=12, max_length=2048)
    reliability_tier: str

    def to_source(self) -> InformationSource:
        if self.reliability_tier not in RELIABILITY_TIERS:
            raise ValueError("Unknown reliability tier")
        return InformationSource(self.source_id, self.name, self.feed_url, self.reliability_tier)




class EvidenceRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=300)
    likelihood_ratio: Decimal = Field(gt=0)
    independence_group: str = Field(min_length=1, max_length=200)
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)


class ForecastRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=200)
    outcome: str = Field(min_length=1, max_length=200)
    prior_alpha: Decimal = Field(default=Decimal("1"), gt=0)
    prior_beta: Decimal = Field(default=Decimal("1"), gt=0)
    evidence: list[EvidenceRequest] = Field(default_factory=list, max_length=100)
    lower_bound: Decimal = Field(ge=0, le=1)
    upper_bound: Decimal = Field(ge=0, le=1)
    confidence: Decimal = Field(ge=0, le=1)
    model_id: str = Field(default="manual_bayesian_evidence", min_length=1, max_length=100)
    model_version: str = Field(default="0.2.0", min_length=1, max_length=50)


class OpportunityRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=200)
    token_id: str = Field(min_length=1, max_length=200)
    outcome_probability: Decimal = Field(ge=0, le=1)
    side: Side
    quantity: Decimal = Field(gt=0)
    fee_rate: Decimal = Field(default=Decimal("0"), ge=0)
    limit_price: Decimal = Field(gt=0, le=1)
    max_book_age_seconds: int = Field(default=30, ge=0, le=300)




class CompleteSetLegRequest(BaseModel):
    outcome: str = Field(min_length=1, max_length=200)
    token_id: str = Field(min_length=1, max_length=200)
    fee_rate: Decimal = Field(default=Decimal("0"), ge=0)


class CompleteSetRequest(BaseModel):
    market_id: str = Field(min_length=1, max_length=200)
    expected_outcomes: list[str] = Field(min_length=2, max_length=20)
    legs: list[CompleteSetLegRequest] = Field(min_length=2, max_length=20)
    quantity: Decimal = Field(gt=0)
    outcomes_verified_exhaustive: bool = False
    settlement_rules_verified: bool = False
    max_book_age_seconds: int = Field(default=30, ge=0, le=300)


class PortfolioRequest(BaseModel):
    expected_excess_returns: list[Decimal] = Field(min_length=1, max_length=100)
    covariance: list[list[Decimal]] = Field(min_length=1, max_length=100)
    max_single_fraction: Decimal = Field(default=Decimal("0.02"), gt=0, le=1)
    max_total_fraction: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)


class PaperOrderRequest(BaseModel):
    market_id: str
    outcome: str = Field(default="YES", pattern="^(YES|NO)$")
    token_id: str
    side: Side
    limit_price: Decimal = Field(gt=0, lt=1)
    quantity: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=12, max_length=128)
    probability: Decimal = Field(ge=0, le=1)
    lower_bound: Decimal = Field(ge=0, le=1)
    upper_bound: Decimal = Field(ge=0, le=1)
    confidence: Decimal = Field(ge=0, le=1)
    model_id: str = "operator_supplied_paper_test"
    model_version: str = "0.2.0"
    fee_rate: Decimal = Field(default=Decimal("0"), ge=0)
    fee_schedule_attested: bool = False
    requested_kelly_fraction: Decimal = Field(default=Decimal("0.005"), ge=0, le=1)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    db_ok = await store.health() if store.pool else False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok,
            "mode": "paper_only", "live_execution": False}


@app.get("/v1/system", dependencies=[Depends(require_owner)])
async def system_status() -> dict[str, Any]:
    return {
        "name": "ORACLE", "version": "0.5.0", "environment": settings.environment,
        "deployment_type": "private_single_owner", "mode": "paper",
        "live_execution_enabled": False,
        "autonomous_acceptance_test_ready": AUTONOMOUS_ACCEPTANCE_TEST_READY,
        "autonomous_acceptance_test_locked": not AUTONOMOUS_ACCEPTANCE_TEST_READY,
        "live_legal_review_approved": settings.live_legal_review_approved,
        "agent": agent.status(),
        "paper_account": paper_account.snapshot(),
    }


@app.get("/v1/geoblock", dependencies=[Depends(require_owner)])
async def geoblock() -> dict[str, Any]:
    try:
        return await client.geoblock()
    except Exception as exc:
        return {"status": "unknown", "trading_allowed": False,
                "reason": f"Geoblock check failed closed: {type(exc).__name__}"}


@app.get("/v1/markets", dependencies=[Depends(require_owner)])
async def markets(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    try:
        rows = await client.markets(limit=min(max(limit, 1), 500), offset=max(offset, 0))
        for row in rows:
            await store.upsert_market(row)
        return {"data": rows, "meta": {"count": len(rows), "offset": offset}}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market data unavailable: {type(exc).__name__}") from exc


@app.get("/v1/markets/{market_id}", dependencies=[Depends(require_owner)])
async def market_detail(market_id: str) -> dict[str, Any]:
    try:
        return await client.market(market_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market lookup failed: {type(exc).__name__}") from exc


@app.get("/v1/orderbooks/{token_id}", dependencies=[Depends(require_owner)])
async def order_book(token_id: str) -> dict[str, Any]:
    try:
        book = await client.order_book(token_id)
        return {
            "market_id": book.market_id, "token_id": book.token_id,
            "captured_at": book.captured_at.isoformat(), "age_seconds": str(book.age_seconds()),
            "best_bid": str(book.best_bid) if book.best_bid is not None else None,
            "best_ask": str(book.best_ask) if book.best_ask is not None else None,
            "midpoint": str(book.midpoint) if book.midpoint is not None else None,
            "bids": [{"price": str(x.price), "size": str(x.size)} for x in book.bids],
            "asks": [{"price": str(x.price), "size": str(x.size)} for x in book.asks],
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Order book unavailable: {type(exc).__name__}") from exc


@app.get("/v1/wallets/leaderboard", dependencies=[Depends(require_owner)])
async def leaderboard(limit: int = 100, time_period: str = "all", cursor: str | None = None) -> dict[str, Any]:
    try:
        return await client.leaderboard(min(max(limit, 1), 500), time_period, cursor)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Wallet leaderboard unavailable: {type(exc).__name__}") from exc




@app.get("/v1/wallets/{wallet_address}/trades", dependencies=[Depends(require_owner)])
async def wallet_trade_page(wallet_address: str, limit: int = 100,
                            cursor: str | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet_address):
        raise HTTPException(status_code=422, detail="wallet_address must be a 20-byte EVM address")
    try:
        return await client.wallet_trades(wallet_address.lower(), min(max(limit, 1), 1000), cursor)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Wallet trade retrieval failed: {type(exc).__name__}") from exc


@app.post("/v1/wallets/discover", dependencies=[Depends(require_owner)])
async def discover_wallets_endpoint(target: int = 5_000,
                                    max_leaderboard_pages: int = 100,
                                    max_market_pages: int = 100) -> dict[str, Any]:
    target = min(max(target, 1), 10_000)
    try:
        report = await discover_wallets(
            client, store, target=target,
            max_leaderboard_pages=min(max(max_leaderboard_pages, 1), 500),
            max_market_pages=min(max(max_market_pages, 1), 500),
        )
        result = report.to_dict()
        await store.audit("WALLET_DISCOVERY_RUN", "oracle", "wallet_registry", None, result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Wallet discovery failed: {type(exc).__name__}") from exc


@app.get("/v1/wallets/ingestion-status", dependencies=[Depends(require_owner)])
async def wallet_ingestion_status() -> dict[str, Any]:
    return await store.wallet_ingestion_status()


@app.post("/v1/wallets/score", dependencies=[Depends(require_owner)])
async def score_wallet_batch(max_wallets: int = 100) -> dict[str, Any]:
    score_version = "wallet-evidence-0.5.0"
    addresses = await store.list_wallets_needing_score(score_version, min(max(max_wallets, 1), 250))
    scored: list[dict[str, Any]] = []
    for address in addresses:
        rows = await store.wallet_trade_rows(address)
        trades = [WalletTrade(
            trade_id=str(row["trade_id"]), wallet_address=address,
            market_id=str(row["market_id"]), token_id=str(row["token_id"]),
            side=Side(str(row["side"]).upper()), price=Decimal(str(row["price"])),
            quantity=Decimal(str(row["quantity"])), fee=Decimal(str(row["fee"])),
            executed_at=row["executed_at"], fee_known=bool(row["fee_known"]),
        ) for row in rows]
        # Trade-feed pagination completion does not prove opening balances, transfers,
        # redemptions, rewards or all fee information. Never attest full P&L here.
        reconstruction = reconstruct_wallet(
            trades, current_marks={}, history_complete=False, initial_balances_known=False,
        )
        result = score_wallet(reconstruction)
        await store.save_wallet_score(address, result, score_version)
        scored.append({
            "wallet_address": address, "trade_count": reconstruction.trade_count,
            "fees_complete": reconstruction.fees_complete,
            "evidence_status": result.evidence_status,
            "score": str(result.score), "confidence": str(result.confidence),
            "observed_weight": str(result.observed_weight),
            "components": {key: str(value) if value is not None else None
                           for key, value in result.components.items()},
            "classification": result.classification,
            "warnings": list(result.warnings),
        })
    await store.audit("WALLET_EVIDENCE_SCORED", "oracle", "wallet_scores", None, {
        "score_version": score_version, "wallets_scored": len(scored),
    })
    return {"score_version": score_version, "wallets_scored": len(scored),
            "results": scored,
            "warning": "These are provisional evidence profiles, not verified skilled-wallet rankings."}


@app.post("/v1/wallets/ingest-trades", dependencies=[Depends(require_owner)])
async def ingest_wallet_trades_endpoint(max_wallets: int = 25,
                                        max_pages_per_wallet: int = 20) -> dict[str, Any]:
    try:
        result = await ingest_wallet_trade_history(
            client, store, max_wallets=min(max(max_wallets, 1), 100),
            max_pages_per_wallet=min(max(max_pages_per_wallet, 1), 100),
        )
        await store.audit("WALLET_TRADE_INGESTION_RUN", "oracle", "wallet_trades", None, result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Wallet trade ingestion failed: {type(exc).__name__}") from exc


@app.post("/v1/wallets/ingest-activity", dependencies=[Depends(require_owner)])
async def ingest_wallet_activity_endpoint(
    max_wallets: int = 25, max_pages_per_wallet: int = 20, page_size: int = 1_000,
) -> dict[str, Any]:
    try:
        result = await ingest_wallet_activity_history(
            client, store, max_wallets=min(max(max_wallets, 1), 100),
            max_pages_per_wallet=min(max(max_pages_per_wallet, 1), 100),
            page_size=min(max(page_size, 1), 1_000),
        )
        await store.audit("WALLET_ACTIVITY_INGESTION_RUN", "oracle", "wallet_activity", None, result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Wallet activity ingestion failed: {type(exc).__name__}") from exc


@app.post("/v1/paper/session/start", dependencies=[Depends(require_owner)])
async def start_paper_session(request: StartPaperRequest) -> dict[str, Any]:
    global active_session, agent_task, paper_account
    if not AUTONOMOUS_ACCEPTANCE_TEST_READY:
        raise HTTPException(
            status_code=409,
            detail="The 12-hour autonomous acceptance test is locked. The current build is not yet an accepted autonomous dummy-test candidate.",
        )
    if active_session and active_session.state == SessionState.RUNNING:
        raise HTTPException(status_code=409, detail="A paper session is already running")
    bankroll = request.bankroll if request.bankroll is not None else settings.paper_initial_bankroll
    if bankroll <= 0:
        raise HTTPException(status_code=422, detail="Bankroll must be positive")
    active_session = PaperSession.start(request.hours)
    paper_account = PaperAccount.create(bankroll)
    await store.start_session(active_session, str(bankroll))
    await store.save_paper_account(active_session.session_id, paper_account.snapshot())
    await store.audit("PAPER_SESSION_STARTED", "owner", "paper_session", active_session.session_id,
                      {"hours": request.hours, "bankroll": str(bankroll), "mode": "paper"})
    agent_task = asyncio.create_task(agent.run_session(active_session))
    return {"session_id": active_session.session_id, "state": active_session.state.value,
            "started_at": active_session.started_at, "ends_at": active_session.ends_at,
            "bankroll": str(bankroll), "execution_mode": "paper"}


@app.post("/v1/paper/session/stop", dependencies=[Depends(require_owner)])
async def stop_paper_session(request: StopRequest) -> dict[str, Any]:
    if not active_session:
        raise HTTPException(status_code=404, detail="No paper session exists")
    active_session.stop()
    await store.update_session(active_session)
    await store.audit("PAPER_SESSION_STOPPED", "owner", "paper_session", active_session.session_id,
                      {"reason": request.reason})
    return {"session_id": active_session.session_id, "state": active_session.state.value}


@app.get("/v1/paper/session", dependencies=[Depends(require_owner)])
async def paper_session_status() -> dict[str, Any]:
    return {**agent.status(), "account": paper_account.snapshot()}


@app.post("/v1/paper/orders", dependencies=[Depends(require_owner)])
async def submit_paper_order(request: PaperOrderRequest) -> dict[str, Any]:
    if not store.pool:
        raise HTTPException(status_code=503, detail="Paper order path requires PostgreSQL for durable idempotency and audit")
    if not active_session or active_session.state != SessionState.RUNNING:
        raise HTTPException(status_code=409, detail="Paper orders require an active test session")
    if request.lower_bound > request.probability or request.probability > request.upper_bound:
        raise HTTPException(status_code=422, detail="Forecast bounds must contain probability")
    try:
        book = await client.order_book(request.token_id, request.market_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Fresh order book unavailable") from exc
    persisted = await store.create_paper_order(active_session.session_id, request.model_dump(mode="json"))
    if not persisted["created"]:
        existing = persisted.get("existing") or {}
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_INTENT",
                                                     "status": existing.get("status", "already_exists"),
                                                     "paper_order_id": persisted.get("paper_order_id")})
    paper_order_id = persisted.get("paper_order_id")
    intent = OrderIntent(request.market_id, request.token_id, request.side, request.limit_price,
                         request.quantity, request.idempotency_key, model_id=request.model_id)
    forecast = Forecast(request.market_id, request.outcome, request.probability, request.lower_bound,
                        request.upper_bound, request.confidence, request.model_id,
                        request.model_version, validated=False)
    fee_cost_per_share = request.limit_price * request.fee_rate
    # Probability is for the selected token outcome. A buy benefits from fair value
    # above price; a sell benefits from executable price above fair value.
    net_ev = ((request.probability - request.limit_price - fee_cost_per_share)
              if request.side == Side.BUY else
              (request.limit_price - request.probability - fee_cost_per_share))
    decision = risk_engine.evaluate_paper(intent, forecast, book, paper_account,
                                          request.requested_kelly_fraction, net_ev)
    await store.audit("PAPER_RISK_DECISION", "risk_engine", "paper_order", request.idempotency_key,
                      {"decision": decision.decision.value, "checks_passed": decision.checks_passed,
                       "checks_failed": decision.checks_failed})
    if decision.decision.value != "approve":
        rejected = {"decision": decision.decision.value, "checks_failed": list(decision.checks_failed)}
        await store.finish_paper_order(paper_order_id, "RISK_REJECTED", rejected)
        raise HTTPException(status_code=409, detail={"decision": decision.decision.value,
                                                     "checks_failed": decision.checks_failed})
    execution = paper_broker.execute(intent, book, paper_account, request.fee_rate,
                                     request.fee_schedule_attested)
    await store.audit("PAPER_ORDER_EXECUTED", "paper_broker", "paper_order", request.idempotency_key,
                      {"status": execution.status, "filled_quantity": str(execution.filled_quantity),
                       "average_price": str(execution.average_price) if execution.average_price else None,
                       "fee_total": str(execution.fee_total), "reason": execution.reason})
    execution_payload = {"status": execution.status, "filled_quantity": str(execution.filled_quantity),
                         "remaining_quantity": str(execution.remaining_quantity),
                         "average_price": str(execution.average_price) if execution.average_price else None,
                         "fee_total": str(execution.fee_total), "reason": execution.reason}
    await store.finish_paper_order(paper_order_id, execution.status, execution_payload)
    await store.save_paper_fills(paper_order_id, list(execution.fills))
    await store.save_paper_account(active_session.session_id, paper_account.snapshot())
    active_session.orders_submitted += 1
    await store.update_session(active_session)
    return {"risk_decision": decision, "execution": execution,
            "account": paper_account.snapshot(),
            "notice": "Simulated only; no external order was submitted."}






def build_unvalidated_forecast(request: ForecastRequest) -> Forecast:
    return create_forecast(
        market_id=request.market_id, outcome=request.outcome,
        prior=BetaPrior(request.prior_alpha, request.prior_beta),
        evidence=[EvidenceItem(x.evidence_id, x.likelihood_ratio, x.independence_group, x.confidence)
                  for x in request.evidence],
        lower_bound=request.lower_bound, upper_bound=request.upper_bound,
        confidence=request.confidence, model_id=request.model_id,
        model_version=request.model_version, validated=False,
    )


def forecast_payload(forecast: Forecast) -> dict[str, Any]:
    return {
        "market_id": forecast.market_id, "outcome": forecast.outcome,
        "probability": str(forecast.probability), "lower_bound": str(forecast.lower_bound),
        "upper_bound": str(forecast.upper_bound), "confidence": str(forecast.confidence),
        "model_id": forecast.model_id, "model_version": forecast.model_version,
        "evidence_references": list(forecast.evidence_references), "validated": False,
    }


@app.post("/v1/forecasts/preview", dependencies=[Depends(require_owner)])
async def forecast_preview(request: ForecastRequest) -> dict[str, Any]:
    try:
        forecast = build_unvalidated_forecast(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"forecast": forecast_payload(forecast),
            "notice": "Evidence-weighted calculation only; no model validation or prospective calibration is asserted."}


@app.post("/v1/forecasts", dependencies=[Depends(require_owner)])
async def record_forecast(request: ForecastRequest) -> dict[str, Any]:
    if not store.pool:
        raise HTTPException(status_code=503, detail="Forecast persistence requires PostgreSQL")
    try:
        forecast = build_unvalidated_forecast(request)
        forecast_id = await store.record_forecast(forecast)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Forecast could not be recorded: {type(exc).__name__}") from exc
    await store.audit("FORECAST_RECORDED_UNVALIDATED", "owner", "forecast", forecast_id,
                      {"market_id": forecast.market_id, "model_id": forecast.model_id,
                       "model_version": forecast.model_version, "probability": str(forecast.probability)})
    payload = forecast_payload(forecast)
    payload["forecast_id"] = forecast_id
    return {"forecast": payload, "persisted": True}


@app.post("/v1/opportunities/evaluate", dependencies=[Depends(require_owner)])
async def evaluate_opportunity(request: OpportunityRequest) -> dict[str, Any]:
    try:
        book = await client.order_book(request.token_id, request.market_id)
        result = evaluate_directional(
            outcome_probability=request.outcome_probability, book=book, side=request.side,
            quantity=request.quantity, fee_rate=request.fee_rate, limit_price=request.limit_price,
            max_book_age_seconds=request.max_book_age_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Opportunity evaluation failed: {type(exc).__name__}") from exc
    return {"evaluation": {
        "market_id": result.market_id, "token_id": result.token_id, "side": result.side.value,
        "outcome_probability": str(result.outcome_probability),
        "requested_quantity": str(result.requested_quantity), "filled_quantity": str(result.filled_quantity),
        "average_price": str(result.average_price) if result.average_price is not None else None,
        "notional": str(result.notional), "fee_total": str(result.fee_total),
        "gross_edge_per_share": str(result.gross_edge_per_share) if result.gross_edge_per_share is not None else None,
        "net_edge_per_share": str(result.net_edge_per_share) if result.net_edge_per_share is not None else None,
        "net_expected_value": str(result.net_expected_value) if result.net_expected_value is not None else None,
        "roi": str(result.roi) if result.roi is not None else None,
        "executable": result.executable, "reason": result.reason,
    }, "notice": "Candidate evaluation only. This endpoint does not create an order."}




@app.post("/v1/opportunities/complete-set/evaluate", dependencies=[Depends(require_owner)])
async def evaluate_complete_set_opportunity(request: CompleteSetRequest) -> dict[str, Any]:
    try:
        legs = []
        for leg in request.legs:
            book = await client.order_book(leg.token_id, request.market_id)
            legs.append(OutcomeLeg(leg.outcome, book, leg.fee_rate))
        result = evaluate_complete_set(
            market_id=request.market_id, expected_outcomes=request.expected_outcomes,
            legs=legs, quantity=request.quantity,
            outcomes_verified_exhaustive=request.outcomes_verified_exhaustive,
            settlement_rules_verified=request.settlement_rules_verified,
            max_book_age_seconds=request.max_book_age_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Complete-set evaluation failed: {type(exc).__name__}") from exc
    return {"evaluation": {
        "market_id": result.market_id, "outcomes": list(result.outcomes),
        "quantity": str(result.quantity), "total_cost": str(result.total_cost),
        "total_fees": str(result.total_fees), "guaranteed_payout": str(result.guaranteed_payout),
        "net_profit": str(result.net_profit), "roi": str(result.roi),
        "executable": result.executable, "classification": result.classification,
        "reason": result.reason,
    }, "notice": "Candidate calculation only. Outcome exhaustiveness and settlement semantics are owner attestations; no order is created."}


@app.post("/v1/portfolio/allocate", dependencies=[Depends(require_owner)])
async def portfolio_allocate(request: PortfolioRequest) -> dict[str, Any]:
    try:
        result = mean_variance_kelly_approx(
            request.expected_excess_returns, request.covariance,
            max_single_fraction=request.max_single_fraction,
            max_total_fraction=request.max_total_fraction,
        )
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"fractions": [str(x) for x in result.fractions],
            "expected_return": str(result.expected_return), "variance": str(result.variance),
            "approximate_log_growth": str(result.approximate_log_growth),
            "iterations": result.iterations, "converged": result.converged,
            "notice": "Mean-variance approximation to portfolio Kelly; requires out-of-sample estimates and independent validation."}


@app.post("/v1/news/ingest", dependencies=[Depends(require_owner)])
async def ingest_news(request: RSSIngestRequest) -> dict[str, Any]:
    if not store.pool:
        raise HTTPException(status_code=503, detail="News ingestion requires PostgreSQL")
    try:
        source = request.to_source()
        documents = await rss_ingestor.ingest(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feed ingestion failed: {type(exc).__name__}") from exc
    inserted = await store.save_source_documents(documents)
    await store.audit("RSS_SOURCE_INGESTED", "owner", "source", source.source_id,
                      {"observed": len(documents), "inserted": inserted,
                       "reliability_tier": source.reliability_tier})
    return {"source_id": source.source_id, "observed": len(documents), "inserted": inserted,
            "duplicates": len(documents) - inserted,
            "note": "RSS entries are leads with provenance, not verified facts or extracted claims."}


@app.get("/v1/news/documents", dependencies=[Depends(require_owner)])
async def news_documents(limit: int = 100) -> dict[str, Any]:
    if not store.pool:
        raise HTTPException(status_code=503, detail="News documents require PostgreSQL")
    return {"data": await store.recent_source_documents(min(max(limit, 1), 500))}


@app.get("/v1/audit", dependencies=[Depends(require_owner)])
async def audit_tail(limit: int = 100) -> dict[str, Any]:
    return {"data": await store.audit_tail(min(max(limit, 1), 500))}


@app.get("/v1/audit/verify", dependencies=[Depends(require_owner)])
async def verify_audit() -> dict[str, Any]:
    return await store.verify_audit_chain()


@app.post("/v1/risk/kill-switch", dependencies=[Depends(require_owner)])
async def activate_kill_switch(reason: str = "Operator activated") -> dict[str, Any]:
    risk_engine.kill_switch_active = True
    await store.audit("KILL_SWITCH_ACTIVATED", "owner", "system", "global", {"reason": reason})
    return {"active": True, "reason": reason}
