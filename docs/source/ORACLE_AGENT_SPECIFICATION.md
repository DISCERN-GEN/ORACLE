# ORACLE Agent Specification

| Property | Value |
|---|---|
| Document | ORACLE_AGENT_SPECIFICATION |
| Version | 1.0 |
| Date | 01 November 2026 |
| Status | Engineering baseline |
| Parent document | ORACLE Engineering Blueprint v1.0 |
| Nature | Persistent autonomous research & decision agent |

---

## 1. Purpose

The ORACLE agent is a long-running process that observes markets and information, investigates relevant developments, forms independent probability views, evaluates opportunities, and submits order intents only through the deterministic risk and execution gateways.

It is **not** a simple rule engine and **not** an unrestricted LLM with trading privileges.

---

## 2. Core Capabilities

The agent must be able to:

1. Discover new opportunities and decide which events require investigation.
2. Select relevant information sources and retrieve historical wallet intelligence.
3. Identify affected markets and map resolution criteria accurately.
4. Challenge contradictory information and maintain evidence provenance.
5. Request probability estimates from the forecasting service.
6. Compare independent estimates against executable prices.
7. Calculate risk-adjusted allocations (via the quantitative core).
8. Monitor active positions and detect invalidated theses.
9. Recommend position reductions or exits.
10. Learn from resolved outcomes and update internal memory.

---

## 3. Component Architecture

| Component | Responsibility |
|---|---|
| **Planner** | Selects and prioritises research tasks |
| **Evidence Manager** | Tracks sources, claims, confidence and contradictions |
| **Event Analyser** | Interprets events and extracts structured claims |
| **Market Mapper** | Aligns events to exact market resolution rules |
| **Wallet Analyst** | Retrieves and interprets historical trader intelligence |
| **Forecast Coordinator** | Orchestrates calls to probability models |
| **Opportunity Evaluator** | Computes EV, arbitrage and candidate rankings |
| **Risk Client** | Requests independent risk approval (never self-approves) |
| **Execution Monitor** | Tracks order state and position health |
| **Learning Service** | Evaluates outcomes and updates memory / model feedback |

All components communicate through well-defined internal interfaces and shared structured memory.

---

## 4. Decision Lifecycle (State Machine)

```
IDLE
  │
  ▼
OBSERVE ──────────────────────────────┐
  │                                   │
  ▼                                   │
DETECT_RELEVANT_CHANGE                │
  │                                   │
  ▼                                   │
INVESTIGATE_SOURCES                   │
  │                                   │
  ▼                                   │
IDENTIFY_AFFECTED_MARKETS             │
  │                                   │
  ▼                                   │
ANALYSE_WALLET_BEHAVIOUR              │
  │                                   │
  ▼                                   │
ESTIMATE_INDEPENDENT_PROBABILITY      │
  │                                   │
  ▼                                   │
CHALLENGE_ASSUMPTIONS                 │
  │                                   │
  ▼                                   │
CALCULATE_EXPECTED_VALUE              │
  │                                   │
  ▼                                   │
EVALUATE_ARBITRAGE                    │
  │                                   │
  ▼                                   │
CALCULATE_KELLY_ALLOCATION            │
  │                                   │
  ▼                                   │
REQUEST_RISK_APPROVAL                 │
  │                                   │
  ├── REJECT ──► RECORD_NO_TRADE ──► IDLE
  │
  ├── WATCH ───► CONTINUE_MONITORING ─► OBSERVE
  │
  └── APPROVE
        │
        ▼
      SUBMIT_ORDER_INTENT
        │
        ▼
      MONITOR_AND_RECONCILE
        │
        ▼
      EVALUATE_OUTCOME
        │
        ▼
      UPDATE_INTELLIGENCE ──────────────► IDLE
```

Transitions are logged to the audit trail with full context.

---

## 5. Reasoning Requirements

For every material decision the agent must be able to answer:

| Question | Required output |
|---|---|
| What happened? | Structured event summary |
| What is known? | Evidence set with provenance |
| What remains uncertain? | Explicit uncertainty list |
| Which markets are affected? | Market IDs + resolution mapping |
| What is the market currently pricing? | Executable prices + timestamp |
| What is the independent probability? | Forecast object with bounds |
| What evidence supports the estimate? | Linked claims / sources |
| What evidence contradicts it? | Counter-evidence |
| What would invalidate the thesis? | Invalidation conditions |
| Is the opportunity executable? | Liquidity, depth, rules check |
| What is the risk-adjusted size? | Kelly / portfolio-constrained size |
| Decision | `trade` / `watch` / `reject` |

---

## 6. Tools Available to the Agent

The agent may call only the following tool categories (implemented as internal service clients):

| Tool category | Examples | Notes |
|---|---|---|
| Market data | Get order book, market rules, mid/spread | Freshness enforced |
| Wallet intelligence | Profile, recent trades, score | Read-only |
| News / events | Search, ingest, evidence retrieval | Provenance required |
| Forecasting | Request forecast, retrieve calibration | Versioned models |
| Opportunity | Evaluate mispricing / arbitrage | Deterministic calc |
| Risk | Request approval | Agent cannot approve itself |
| Execution | Submit intent, cancel, query state | Never signs |
| Memory | Read / write structured memory | Typed memory only |
| Portfolio | Current exposure, open positions | Read-only for agent |

**Forbidden tools / actions**

- Direct access to private keys or signing endpoints
- Modification of hard risk limits
- Direct order submission that bypasses the execution gateway
- Treating web content as system instructions
- Inventing evidence that was not retrieved

---

## 7. Persistent Memory

Memory is stored externally (database `agent_memory` table) and is strongly typed.

### 7.1 Memory Types

| Type | Content |
|---|---|
| `wallet_performance` | Historical metrics and scores |
| `strategy_classification` | Behavioural labels |
| `event_dossier` | Accumulated evidence on an event |
| `market_resolution` | Past resolution outcomes and notes |
| `source_reliability` | Observed accuracy of sources |
| `probability_estimate` | Prior forecasts and outcomes |
| `trading_decision` | Past intents and rationale |
| `failed_prediction` | Error analysis |
| `strategy_performance` | Aggregate strategy results |
| `operator_instruction` | Human directives (highest priority) |
| `model_evaluation` | Calibration and skill metrics |

### 7.2 Memory Item Schema

```json
{
  "memory_id": "uuid",
  "memory_type": "event_dossier",
  "entity_ref": "event-or-market-id",
  "content": {},
  "confidence": 0.0-1.0,
  "source": "component or operator",
  "valid_from": "ISO-8601",
  "valid_until": "ISO-8601 or null",
  "created_at": "ISO-8601"
}
```

Operator instructions override agent-derived memory when conflicts arise.

---

## 8. Autonomy Boundaries (Hard Constraints)

The following are **non-negotiable**:

1. The agent must never directly access private signing credentials.
2. No LLM output can independently authorise a financial transaction.
3. No trade can execute without a fresh risk decision and policy validation.
4. The agent cannot modify `MAX_*` risk limits or kill-switch state.
5. The agent cannot mark an arbitrage as “guaranteed” without settlement verification performed by the quantitative core.
6. The agent cannot invent missing evidence; absence of evidence must be recorded as uncertainty.
7. External web content is treated as data, never as executable instructions.
8. The agent must remain capable of returning `reject` or `watch` when evidence is insufficient.

These boundaries are enforced both by prompt/system design and by the surrounding deterministic services.

---

## 9. Interaction with LLM Layer

- The LLM is used for interpretation, hypothesis generation, source selection, and natural-language summarisation of evidence.
- All numerical outputs that affect capital (probabilities used for sizing, EV, Kelly fractions) must be produced or validated by the quantitative core, not accepted solely from free-form LLM text.
- LLM context windows must not contain private keys, full credential material, or unrestricted system prompts that can be overridden by retrieved content.
- Tool-calling is preferred over free-form generation for any action that touches external state.

---

## 10. Observability of the Agent

Every significant step emits:

- Structured log with `trace_id`, `decision_id`, component name
- Audit event (for decisions that can affect capital)
- Optional metrics (task duration, number of sources consulted, reject reasons)

Dashboards must surface:

- Active research threads
- Recent reject / watch / trade decisions
- Memory growth and stale memory items
- Cases where the agent requested risk approval and was denied

---

## 11. Failure & Degradation Modes

| Condition | Agent behaviour |
|---|---|
| Forecasting service unavailable | Pause new directional decisions; continue monitoring |
| Risk service unavailable | No new order intents; existing positions monitored only |
| Stale market data | Reject any opportunity that relies on that data |
| High model disagreement | Increase uncertainty / reduce size or reject |
| Kill-switch active | Enter read-only observation mode |
| Memory write failure | Fail the current decision path; do not proceed with partial state |

---

## 12. Testing Requirements

- Unit tests for each component’s pure logic.
- Integration tests of the full decision lifecycle with mocked external services.
- Replay tests using historical market + news fixtures (no look-ahead).
- Adversarial tests: contradictory sources, missing data, prompt-injection style content in news.
- Safety tests verifying that the agent cannot emit a live order intent without a valid risk decision.

---

**END OF ORACLE_AGENT_SPECIFICATION v1.0**
