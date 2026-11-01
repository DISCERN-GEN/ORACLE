from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg


class Store:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.dsn:
            self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=8, command_timeout=20)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def health(self) -> bool:
        if not self.pool:
            return False
        return await self.pool.fetchval("SELECT 1") == 1

    async def require_schema(self, version: str = "001_initial") -> None:
        if not self.pool:
            raise RuntimeError("PostgreSQL is required for the private ORACLE service")
        found = await self.pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM schema_migrations WHERE version=$1)", version)
        if not found:
            raise RuntimeError(f"Required database migration {version} is not applied")

    async def apply_migration_file(self, path: str | Path) -> None:
        """Apply a checked-in SQL migration atomically when the service starts."""
        if not self.pool:
            raise RuntimeError("PostgreSQL is required for the private ORACLE service")
        sql = Path(path).read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)

    async def audit(self, event_type: str, actor: str, entity_type: str | None,
                    entity_id: str | None, payload: dict[str, Any]) -> None:
        if not self.pool:
            return
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(772031)")
                previous = await conn.fetchval("SELECT payload_hash FROM audit_events ORDER BY audit_id DESC LIMIT 1")
                chain_input = f"{previous or ''}|{event_type}|{actor}|{entity_type or ''}|{entity_id or ''}|{canonical}"
                digest = hashlib.sha256(chain_input.encode()).hexdigest()
                await conn.execute(
                    """INSERT INTO audit_events(event_type, actor, entity_type, entity_id, payload,
                       payload_hash, previous_hash, created_at)
                       VALUES($1,$2,$3,$4,$5::jsonb,$6,$7,$8)""",
                    event_type, actor, entity_type, entity_id, canonical, digest, previous,
                    datetime.now(timezone.utc),
                )

    async def audit_tail(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            "SELECT audit_id,event_type,actor,entity_type,entity_id,payload,payload_hash,previous_hash,created_at "
            "FROM audit_events ORDER BY audit_id DESC LIMIT $1", limit)
        return [dict(r) for r in rows]

    async def upsert_wallet(self, address: str, source: str = "polymarket_leaderboard",
                            source_ref: str | None = None) -> bool:
        if not self.pool:
            return False
        address = address.lower()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                inserted_row = await conn.fetchrow(
                    """INSERT INTO wallets(address,discovery_source,first_seen,last_seen,activity_status)
                       VALUES($1,$2,NOW(),NOW(),'active')
                       ON CONFLICT(address) DO NOTHING RETURNING wallet_id""",
                    address, source,
                )
                if inserted_row:
                    wallet_id = inserted_row["wallet_id"]
                else:
                    wallet_id = await conn.fetchval(
                        "UPDATE wallets SET last_seen=NOW(),activity_status='active' "
                        "WHERE address=$1 RETURNING wallet_id", address,
                    )
                await conn.execute(
                    """INSERT INTO wallet_discovery_sources(wallet_id,source,source_ref,first_seen,last_seen)
                       VALUES($1,$2,$3,NOW(),NOW())
                       ON CONFLICT(wallet_id,source,source_ref) DO UPDATE SET last_seen=NOW()""",
                    wallet_id, source, str(source_ref or ""),
                )
                return inserted_row is not None

    async def get_checkpoint(self, name: str) -> dict[str, Any] | None:
        if not self.pool:
            return None
        row = await self.pool.fetchrow(
            "SELECT state FROM ingestion_checkpoints WHERE checkpoint_name=$1", name)
        if not row:
            return None
        value = row["state"]
        return json.loads(value) if isinstance(value, str) else dict(value)

    async def set_checkpoint(self, name: str, state: dict[str, Any]) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """INSERT INTO ingestion_checkpoints(checkpoint_name,state,updated_at)
               VALUES($1,$2::jsonb,NOW())
               ON CONFLICT(checkpoint_name) DO UPDATE SET state=EXCLUDED.state,updated_at=NOW()""",
            name, json.dumps(state, default=str),
        )

    async def list_wallet_addresses(self, after_address: str | None = None, limit: int = 100) -> list[str]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            "SELECT address FROM wallets WHERE ($1::text IS NULL OR address>$1) ORDER BY address LIMIT $2",
            after_address, min(max(limit, 1), 1000),
        )
        return [str(row["address"]) for row in rows]

    async def list_wallets_for_trade_ingestion(self, limit: int = 25) -> list[str]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            """SELECT w.address FROM wallets w
               LEFT JOIN ingestion_checkpoints c
                 ON c.checkpoint_name = 'wallet_trade_ingestion:' || w.address
               WHERE COALESCE((c.state->>'complete')::boolean,FALSE)=FALSE
               ORDER BY c.updated_at NULLS FIRST,w.address LIMIT $1""",
            min(max(limit, 1), 1000),
        )
        return [str(row["address"]) for row in rows]

    async def save_wallet_trade(self, trade: dict[str, Any]) -> bool:
        if not self.pool:
            return False
        status = await self.pool.execute(
            """INSERT INTO wallet_trades(trade_id,wallet_id,market_id,token_id,side,price,quantity,
                   fee,executed_at,source_ref,fee_known,raw_data)
               SELECT $1,w.wallet_id,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb
               FROM wallets w WHERE w.address=$2
               ON CONFLICT(trade_id) DO NOTHING""",
            trade["trade_id"], trade["wallet_address"], trade["market_id"], trade["token_id"],
            trade["side"], trade["price"], trade["quantity"], trade["fee"], trade["executed_at"],
            trade.get("source_ref"), bool(trade.get("fee_known", False)),
            json.dumps(trade.get("raw_data", {}), default=str),
        )
        return status.endswith("1")

    async def list_wallets_for_activity_ingestion(self, feed: str, limit: int = 25) -> list[str]:
        if feed not in {"activity", "activity_tips", "activity_combos"}:
            raise ValueError("Unsupported wallet activity feed")
        if not self.pool:
            return []
        prefix = f"wallet_activity:{feed}:"
        rows = await self.pool.fetch(
            """SELECT w.address FROM wallets w
               LEFT JOIN ingestion_checkpoints c
                 ON c.checkpoint_name = $1 || w.address
               WHERE COALESCE((c.state->>'complete')::boolean,FALSE)=FALSE
               ORDER BY c.updated_at NULLS FIRST,w.address LIMIT $2""",
            prefix, min(max(limit, 1), 1000),
        )
        return [str(row["address"]) for row in rows]

    async def save_wallet_activity(self, activity: dict[str, Any]) -> bool:
        if not self.pool:
            return False
        status = await self.pool.execute(
            """INSERT INTO wallet_activity(
                   activity_id,wallet_id,source_feed,activity_type,condition_id,token_id,side,price,size,
                   usdc_size,amount_usdc,payout_usdc,occurred_at,transaction_hash,source_event_id,raw_data)
               SELECT $1,w.wallet_id,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb
               FROM wallets w WHERE w.address=$2
               ON CONFLICT(wallet_id,source_feed,activity_id) DO NOTHING""",
            activity["activity_id"], activity["wallet_address"], activity["source_feed"],
            activity["activity_type"], activity.get("condition_id"), activity.get("token_id"),
            activity.get("side"), activity.get("price"), activity.get("size"),
            activity.get("usdc_size"), activity.get("amount_usdc"), activity.get("payout_usdc"),
            activity["occurred_at"], activity.get("transaction_hash"),
            activity.get("source_event_id"), json.dumps(activity.get("raw_data", {}), default=str),
        )
        return status.endswith("1")

    async def list_wallets_needing_score(self, score_version: str, limit: int = 100) -> list[str]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            """SELECT w.address FROM wallets w
               WHERE EXISTS (SELECT 1 FROM wallet_trades t WHERE t.wallet_id=w.wallet_id)
                 AND NOT EXISTS (
                   SELECT 1 FROM wallet_scores s
                   WHERE s.wallet_id=w.wallet_id AND s.score_version=$1
                     AND s.scored_at >= (SELECT MAX(t2.created_at) FROM wallet_trades t2
                                         WHERE t2.wallet_id=w.wallet_id)
                 )
               ORDER BY w.address LIMIT $2""",
            score_version, min(max(limit, 1), 1000),
        )
        return [str(row["address"]) for row in rows]

    async def wallet_trade_rows(self, address: str) -> list[dict[str, Any]]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            """SELECT t.trade_id,t.market_id,t.token_id,t.side,t.price,t.quantity,t.fee,
                      t.fee_known,t.executed_at
               FROM wallet_trades t JOIN wallets w ON w.wallet_id=t.wallet_id
               WHERE w.address=$1 ORDER BY t.executed_at,t.trade_id""",
            address.lower(),
        )
        return [dict(row) for row in rows]

    async def save_wallet_score(self, address: str, score: Any, score_version: str) -> None:
        if not self.pool:
            return
        c = score.components
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO wallet_scores(wallet_id,score_version,overall_score,
                         oos_predictive_skill,risk_adjusted_return,closing_line_value,consistency,
                         timing_advantage,liquidity_capacity,data_quality,sample_size,
                         statistical_confidence,strategy_classification,evidence_status,
                         observed_weight,warnings,scored_at)
                       SELECT wallet_id,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,NOW()
                       FROM wallets WHERE address=$1""",
                    address.lower(), score_version, score.score,
                    c.get("out_of_sample_skill"), c.get("risk_adjusted_return"),
                    c.get("closing_line_value"), c.get("consistency"),
                    c.get("timing_advantage"), c.get("liquidity_capacity"), c.get("data_quality"),
                    score.sample_size, score.confidence, score.classification,
                    score.evidence_status, score.observed_weight,
                    json.dumps(list(score.warnings)),
                )
                await conn.execute(
                    "UPDATE wallets SET data_quality_score=$2,updated_at=NOW() WHERE address=$1",
                    address.lower(), c.get("data_quality"),
                )

    async def wallet_count(self) -> int:
        if not self.pool:
            return 0
        return int(await self.pool.fetchval("SELECT COUNT(*) FROM wallets"))

    async def wallet_ingestion_status(self) -> dict[str, Any]:
        if not self.pool:
            return {"database_available": False}
        counts = await self.pool.fetchrow(
            """SELECT
                 (SELECT COUNT(*) FROM wallets) AS wallet_count,
                 (SELECT COUNT(*) FROM ingestion_checkpoints
                    WHERE checkpoint_name LIKE 'wallet_trade_ingestion:%'
                      AND COALESCE((state->>'complete')::boolean,FALSE)=TRUE) AS complete_wallets,
                 (SELECT COUNT(*) FROM ingestion_checkpoints
                    WHERE checkpoint_name LIKE 'wallet_trade_ingestion:%'
                      AND COALESCE((state->>'complete')::boolean,FALSE)=FALSE) AS started_incomplete_wallets,
                 (SELECT COUNT(*) FROM wallet_trades) AS trade_count,
                 (SELECT COUNT(*) FROM wallet_trades WHERE fee_known=TRUE) AS fee_known_trade_count,
                 (SELECT COUNT(*) FROM wallet_activity) AS activity_event_count,
                 (SELECT COUNT(*) FROM wallet_activity WHERE source_feed='activity') AS standard_activity_count,
                 (SELECT COUNT(*) FROM wallet_activity WHERE source_feed='activity_combos') AS combo_activity_count,
                 (SELECT COUNT(*) FROM wallet_scores) AS score_count""")
        source_rows = await self.pool.fetch(
            """SELECT s.source,COUNT(DISTINCT s.wallet_id) AS wallet_count
               FROM wallet_discovery_sources s GROUP BY s.source ORDER BY s.source""")
        score_rows = await self.pool.fetch(
            "SELECT evidence_status,COUNT(*) AS wallet_count FROM wallet_scores "
            "GROUP BY evidence_status ORDER BY evidence_status")
        activity_rows = await self.pool.fetch(
            "SELECT source_feed,activity_type,COUNT(*) AS event_count FROM wallet_activity "
            "GROUP BY source_feed,activity_type ORDER BY source_feed,activity_type")
        activity_checkpoint_rows = await self.pool.fetch(
            """SELECT split_part(checkpoint_name,':',2) AS source_feed,
                      COUNT(*) AS wallets_started,
                      COUNT(*) FILTER (WHERE COALESCE((state->>'complete')::boolean,FALSE)) AS wallets_completed,
                      COUNT(*) FILTER (WHERE NOT COALESCE((state->>'complete')::boolean,FALSE)) AS wallets_incomplete
               FROM ingestion_checkpoints WHERE checkpoint_name LIKE 'wallet_activity:%'
               GROUP BY split_part(checkpoint_name,':',2) ORDER BY source_feed""")
        activity_checkpoints = await self.pool.fetch(
            """SELECT checkpoint_name,state,updated_at FROM ingestion_checkpoints
               WHERE checkpoint_name LIKE 'wallet_activity:%'
               ORDER BY checkpoint_name LIMIT 100""")
        checkpoints = await self.pool.fetch(
            """SELECT checkpoint_name,state,updated_at FROM ingestion_checkpoints
               WHERE checkpoint_name LIKE 'wallet_discovery:%'
               ORDER BY checkpoint_name""")
        count_values = {key: int(value) for key, value in dict(counts).items()}
        count_values["wallets_not_started_for_trade_ingestion"] = max(
            0, count_values["wallet_count"] - count_values["complete_wallets"]
            - count_values["started_incomplete_wallets"]
        )
        count_values["wallets_without_terminal_trade_history_walk"] = max(
            0, count_values["wallet_count"] - count_values["complete_wallets"]
        )
        return {
            "database_available": True,
            **count_values,
            "discovery_sources": [dict(row) for row in source_rows],
            "scores_by_evidence_status": [dict(row) for row in score_rows],
            "activity_by_feed_and_type": [dict(row) for row in activity_rows],
            "activity_ingestion_by_feed": [
                {**dict(row),
                 "wallets_not_started": max(0, count_values["wallet_count"] - int(row["wallets_started"]))}
                for row in activity_checkpoint_rows
            ],
            "activity_checkpoints_sample": [
                {"name": row["checkpoint_name"],
                 "state": json.loads(row["state"]) if isinstance(row["state"], str) else dict(row["state"]),
                 "updated_at": row["updated_at"].isoformat()}
                for row in activity_checkpoints
            ],
            "discovery_checkpoints": [
                {"name": row["checkpoint_name"],
                 "state": json.loads(row["state"]) if isinstance(row["state"], str) else dict(row["state"]),
                 "updated_at": row["updated_at"].isoformat()}
                for row in checkpoints
            ],
        }

    async def upsert_market(self, market: dict[str, Any]) -> None:
        if not self.pool:
            return
        market_id = str(market.get("id", ""))
        if not market_id:
            return
        await self.pool.execute(
            """INSERT INTO markets(market_id,condition_id,question,description,rules_text,category,status,
                   outcome_labels,outcome_token_ids,open_time,close_time,raw_metadata,created_at,updated_at)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12::jsonb,NOW(),NOW())
               ON CONFLICT(market_id) DO UPDATE SET condition_id=EXCLUDED.condition_id,
               question=EXCLUDED.question,description=EXCLUDED.description,rules_text=EXCLUDED.rules_text,
               category=EXCLUDED.category,status=EXCLUDED.status,outcome_labels=EXCLUDED.outcome_labels,
               outcome_token_ids=EXCLUDED.outcome_token_ids,close_time=EXCLUDED.close_time,
               raw_metadata=EXCLUDED.raw_metadata,updated_at=NOW()""",
            market_id, market.get("conditionId"), market.get("question", "Unknown market"),
            market.get("description"), market.get("resolutionSource"), market.get("category"),
            "closed" if market.get("closed") else "open",
            json.dumps(market.get("outcomes", [])), json.dumps(market.get("clobTokenIds", [])),
            _parse_datetime(market.get("startDate")), _parse_datetime(market.get("endDate")),
            json.dumps(market, default=str),
        )

    async def start_session(self, session: Any, bankroll: str) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """INSERT INTO paper_sessions(session_id,started_at,ends_at,state,heartbeat_at,observations,
               orders_submitted,errors,initial_bankroll) VALUES($1,$2,$3,$4,$5,0,0,0,$6)""",
            uuid.UUID(session.session_id), session.started_at, session.ends_at, session.state.value,
            session.heartbeat_at, bankroll,
        )

    async def update_session(self, session: Any) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """UPDATE paper_sessions SET state=$2,heartbeat_at=$3,observations=$4,
               orders_submitted=$5,errors=$6 WHERE session_id=$1""",
            uuid.UUID(session.session_id), session.state.value, session.heartbeat_at,
            session.observations, session.orders_submitted, session.errors,
        )


    async def save_orderbook(self, book: Any) -> None:
        if not self.pool:
            return
        bids = [{"price": str(x.price), "size": str(x.size)} for x in book.bids]
        asks = [{"price": str(x.price), "size": str(x.size)} for x in book.asks]
        best_bid = book.best_bid
        best_ask = book.best_ask
        midpoint = book.midpoint
        spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
        await self.pool.execute(
            """INSERT INTO orderbook_snapshots(market_id,token_id,bids,asks,best_bid,best_ask,mid_price,
               spread,captured_at,source) VALUES($1,$2,$3::jsonb,$4::jsonb,$5,$6,$7,$8,$9,'clob_rest')""",
            book.market_id, book.token_id, json.dumps(bids), json.dumps(asks), best_bid, best_ask,
            midpoint, spread, book.captured_at,
        )

    async def create_paper_order(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not self.pool:
            return {"created": True, "paper_order_id": None, "existing": None}
        key = str(request["idempotency_key"])
        row = await self.pool.fetchrow(
            """INSERT INTO paper_orders(session_id,idempotency_key,market_id,token_id,side,limit_price,
               quantity,status,request) VALUES($1,$2,$3,$4,$5,$6,$7,'PENDING',$8::jsonb)
               ON CONFLICT(idempotency_key) DO NOTHING
               RETURNING paper_order_id""",
            uuid.UUID(session_id), key, request["market_id"], request["token_id"], request["side"],
            request["limit_price"], request["quantity"], json.dumps(request, default=str),
        )
        if row:
            return {"created": True, "paper_order_id": str(row["paper_order_id"]), "existing": None}
        existing = await self.pool.fetchrow(
            "SELECT paper_order_id,status,result FROM paper_orders WHERE idempotency_key=$1", key)
        return {"created": False, "paper_order_id": str(existing["paper_order_id"]),
                "existing": dict(existing) if existing else None}

    async def finish_paper_order(self, paper_order_id: str | None, status: str,
                                 result: dict[str, Any]) -> None:
        if not self.pool or not paper_order_id:
            return
        await self.pool.execute(
            "UPDATE paper_orders SET status=$2,result=$3::jsonb WHERE paper_order_id=$1",
            uuid.UUID(paper_order_id), status, json.dumps(result, default=str),
        )

    async def save_paper_account(self, session_id: str, snapshot: dict[str, Any]) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            "INSERT INTO paper_account_snapshots(session_id,account) VALUES($1,$2::jsonb)",
            uuid.UUID(session_id), json.dumps(snapshot),
        )

    async def latest_paper_session(self) -> dict[str, Any] | None:
        if not self.pool:
            return None
        row = await self.pool.fetchrow(
            "SELECT * FROM paper_sessions ORDER BY started_at DESC LIMIT 1")
        return dict(row) if row else None



    async def record_forecast(self, forecast: Any) -> str:
        if not self.pool:
            raise RuntimeError("PostgreSQL is required to persist forecasts")
        await self.pool.execute(
            """INSERT INTO model_versions(model_id,model_version,description,is_active)
               VALUES($1,$2,'Owner-supplied Bayesian evidence preview; not validated',FALSE)
               ON CONFLICT(model_id,model_version) DO NOTHING""",
            forecast.model_id, forecast.model_version,
        )
        row = await self.pool.fetchrow(
            """INSERT INTO forecasts(market_id,outcome,probability,lower_bound,upper_bound,confidence,
               model_id,model_version,evidence_references,invalidation_conditions,forecast_time)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,NOW()) RETURNING forecast_id""",
            forecast.market_id, forecast.outcome, forecast.probability, forecast.lower_bound,
            forecast.upper_bound, forecast.confidence, forecast.model_id, forecast.model_version,
            json.dumps(list(forecast.evidence_references)), json.dumps(list(forecast.invalidation_conditions)),
        )
        return str(row["forecast_id"])

    async def save_source_documents(self, documents: list[Any]) -> int:
        if not self.pool or not documents:
            return 0
        inserted = 0
        for doc in documents:
            status = await self.pool.execute(
                """INSERT INTO source_documents(source_type,source_name,url,title,published_at,
                   observed_at,content_hash,summary,reliability_tier)
                   VALUES('rss',$1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT(content_hash) DO NOTHING""",
                doc.source_name, doc.link, doc.title, doc.published_at, doc.observed_at,
                doc.content_hash, doc.summary, doc.reliability_tier,
            )
            if status.endswith("1"):
                inserted += 1
        return inserted

    async def recent_source_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.pool:
            return []
        rows = await self.pool.fetch(
            "SELECT document_id,source_type,source_name,url,title,published_at,observed_at,"
            "content_hash,summary,reliability_tier FROM source_documents "
            "ORDER BY observed_at DESC LIMIT $1", limit)
        return [dict(row) for row in rows]

    async def save_paper_fills(self, paper_order_id: str | None, fills: list[Any]) -> None:
        if not self.pool or not paper_order_id or not fills:
            return
        await self.pool.executemany(
            "INSERT INTO paper_fills(paper_order_id,price,quantity,fee) VALUES($1,$2,$3,$4)",
            [(uuid.UUID(paper_order_id), fill.price, fill.quantity, fill.fee) for fill in fills],
        )

    async def fail_interrupted_sessions(self) -> None:
        if not self.pool:
            return
        # This process does not resume in-memory account/session state after restart.
        await self.pool.execute(
            "UPDATE paper_sessions SET state='failed', "
            "report=COALESCE(report, '{}'::jsonb) || "
            "jsonb_build_object('failure_reason','process_restart') WHERE state='running'")

    async def verify_audit_chain(self) -> dict[str, Any]:
        if not self.pool:
            return {"verified": False, "reason": "database_unavailable", "checked": 0}
        rows = await self.pool.fetch(
            "SELECT event_type,actor,entity_type,entity_id,payload,payload_hash,previous_hash "
            "FROM audit_events ORDER BY audit_id ASC")
        previous: str | None = None
        for index, row in enumerate(rows, start=1):
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
            chain_input = f"{previous or ''}|{row['event_type']}|{row['actor']}|{row['entity_type'] or ''}|{row['entity_id'] or ''}|{canonical}"
            digest = hashlib.sha256(chain_input.encode()).hexdigest()
            if row["previous_hash"] != previous or row["payload_hash"] != digest:
                return {"verified": False, "checked": index, "broken_at": index}
            previous = digest
        return {"verified": True, "checked": len(rows), "head_hash": previous}



def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

    async def save_clob_raw_frame(self, raw_payload: Any, connection_id: str,
                                  received_at: datetime, monotonic_ns: int,
                                  frame_type: str = "json") -> int | None:
        """Durably archive a socket frame before JSON decoding or event parsing."""
        if not self.pool:
            return None
        payload = json.dumps(raw_payload, ensure_ascii=False, default=str)
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO clob_market_messages(
                       connection_id,subscription_version,event_type,received_at,
                       received_monotonic_ns,parser_version,raw_payload,parse_valid,raw_frame_type)
                   VALUES($1,'assets_ids-market-v1','raw_frame',$2,$3,'raw-before-parse-v1',$4::jsonb,FALSE,$5)
                   RETURNING message_id""",
                connection_id, received_at, monotonic_ns, payload, frame_type,
            )

    async def finalize_clob_raw_frame(self, message_id: int, event: dict[str, Any] | None,
                                     parser_error: str | None = None) -> None:
        """Attach parse result to an already durable raw frame; never drops unknown frames."""
        if not self.pool:
            return
        if event is None:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE clob_market_messages SET parser_error=$2, invalidation_reason=$2 WHERE message_id=$1",
                    message_id, parser_error or "non_json_or_unrecognized_frame",
                )
            return
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """UPDATE clob_market_messages SET asset_id=$2,condition_id=$3,event_type=$4,
                           venue_timestamp=$5,book_hash=$6,parser_version=$7,parse_valid=$8,
                           invalidation_reason=$9,payload_sha256=$10,parser_error=$11
                       WHERE message_id=$1""",
                    message_id, event.get("asset_id"), event.get("condition_id"), event["event_type"],
                    event.get("venue_timestamp"), event.get("book_hash"), event["parser_version"],
                    bool(event.get("parse_valid")), event.get("invalidation_reason"),
                    event.get("payload_sha256"), parser_error,
                )
                if event.get("event_type") == "book" and event.get("parse_valid"):
                    await conn.execute(
                        """INSERT INTO clob_book_snapshots(
                               asset_id,condition_id,venue_timestamp,received_at,received_monotonic_ns,
                               book_hash,bids,asks,source_message_id,parser_version,state_valid)
                           VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,TRUE)""",
                        event["asset_id"], event.get("condition_id"), event.get("venue_timestamp"),
                        event["received_at"], event.get("received_monotonic_ns"), event.get("book_hash"),
                        json.dumps(event["bids"]), json.dumps(event["asks"]), message_id,
                        event["parser_version"],
                    )

    async def record_clob_capture_gap(self, connection_id: str, started_at: datetime,
                                      ended_at: datetime, reason: str,
                                      affected_asset_ids: list[str], attempt: int,
                                      recovered_at: datetime | None = None) -> None:
        if not self.pool:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO clob_capture_gaps(
                       connection_id,started_at,ended_at,reason,affected_asset_ids,connection_attempt,recovered_at)
                   VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)""",
                connection_id, started_at, ended_at, reason, json.dumps(affected_asset_ids), attempt,
                recovered_at,
            )

    async def save_clob_market_message(self, event: dict[str, Any]) -> int | None:
        """Compatibility helper for parsed test fixtures and controlled imports."""
        message_id = await self.save_clob_raw_frame(
            event["raw_payload"], event["connection_id"], event["received_at"],
            int(event.get("received_monotonic_ns") or 0),
        )
        if message_id is not None:
            await self.finalize_clob_raw_frame(message_id, event)
        return message_id
