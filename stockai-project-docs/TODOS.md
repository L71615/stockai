# StockAI TODOS

> Backlog for items explicitly deferred from the PROMOTED plan
> `docs/designs/research-decision-loop.md`. Each entry lists blocker
> prerequisites and where to start.

## Deferred (current plan scope)

### P2 / L — Full order & fill simulation
**What:** Realistic partial-fill simulator layered on the shadow_portfolio ledger.
**Why:** Without partial fills the shadow ledger cannot answer "did the
    signal survive realistic queue position", but the v1 evidence loop does
    not need this to prove the signal exists.
**Pros:** Closes the largest remaining gap between paper and live trading.
**Cons:** Replay correctness is hard; needs broker-aligned reference data.
**Depends on:** Stable shadow_portfolio_snapshots (T4) + A-share execution
    fixtures + D7 typed errors extended with `OrderNotFilledError`.
**Start:** Carve a `services/fill_simulator.py` reading shadow order events;
    one adjustable slippage model.
**Source:** Plan section "Deferred to TODOS.md" (#1); outside voice flagged as
    long-run scope.

### P2 / M — Factor / model drift monitoring (PSI / KL)
**What:** Versioned drift_policy + PSI / KL metrics for factor_snapshot and
    ML model input distributions.
**Why:** A signal that silently drifts stops working; without drift detection
    no one notices retirement. v1 evidence loop is the prerequisite — need
    forward snapshots before drift thresholds are meaningful.
**Pros:** Tracks the buried signal decay path the user already monitors for
    `factor_lifecycle`.
**Cons:** False positives on regime shift; needs guardrails.
**Depends on:** Forward snapshot history (T1), `factor_snapshot` version
    policy (D6), baseline distribution per regime.
**Start:** Define `drift_policy.py` with two fixed PSI thresholds, evaluate
    on existing factor_snapshot cache, log to pipeline warnings; do not
    retire automatically.
**Source:** Plan section "Deferred to TODOS.md" (#2).

### P2 / M — CSI300 daily series source (`index_kline` table)
**What:** Versioned CSI300 daily close/return table so shadow_portfolio
    uses the real index instead of the 510300 ETF proxy in
    `strategy_backtest_service._get_benchmark_curve`.
**Why:** Dual baseline policy names CSI300 total return as one of the two
    baselines; today only ETF proxy is available. A real series removes the
    proxy's tracking error (~0.5-1%/yr) from every Gate result.
**Pros:** Honest baseline; necessary precondition for any peer comparison.
**Cons:** Sync cadence; stale-by-one-day is fine, frozen-by-month is not.
**Depends on:** akshare `stock_zh_index_daily` adapter or Futu HIS; choose
    one and add a `index_kline(code, trade_date, close, ...)` table in
    `database.py` and `database/schema.sql`.
**Start:** Add `index_kline` table; backfill ~5y; replace
    `get_benchmark_comparison` first baseline with `index_kline` reads.
**Source:** Plan section "What already exists — dual baseline"; cross-model
    tension D15 / outside voice finding #6.

### P2 / L — Remaining Alpha158 factors
**What:** Continue from 55 → 158 via GP-mined + manually-curated factors.
**Why:** The missing 103 Alpha158 factors exist in the literature; v1 evidence
    loop is the validation protocol they would enter.
**Pros:** Expands the candidate pool under a reliable gate.
**Cons:** Most Alpha158 factors are stylistic duplicates of existing ones;
    incremental value is bounded.
**Depends on:** Working validation ledger (T1) and OOS replay (T2). Every
    new factor must enter via the experiment ledger, not ad-hoc inserts.
**Start:** Pick a 20-factor batch, run through `factor_expr.gp_mine()`,
    validate through the existing Gate.
**Source:** Plan section "Deferred to TODOS.md" (#3).

### P3 / L — Cross-market validation
**What:** Add at least one non-A-share market adapter to validate the
    signal is not regime-specific.
**Why:** Single-market signals bias to A-share microstructure; the protocol
    improvement is real but the market-specific data work is substantial.
**Pros:** Catches single-market bias.
**Cons:** Heavy adapter work; needed only after A-share evidence is credible.
**Depends on:** Stable A-share Gate results (≥1 Champion), shared
    validation_policy (T3) which is already market-aware.
**Start:** Pick HK or US (one), add adapter, run one validation matrix.
**Source:** Plan section "Deferred to TODOS.md" (#4).

### P3 / XL — Online learning
**What:** Auto-update ML factors from rolling windows under drift guard.
**Why:** A six-month-old ML factor is wrong; but auto-update is exactly the
    thing the v1 evidence loop exists to police.
**Pros:** Closes the loop on stale ML models.
**Cons:** Catastrophic if drift detection fails; this is the *last* thing,
    not the *first*.
**Depends on:** Drift policy (above), shadow record durability, model
    version registry, rehearsed rollback.
**Start:** Offline replay of would-be-online updates first; never enable
    auto-update before successful dry-run for one full window.
**Source:** Plan section "Deferred to TODOS.md" (#5).

### P2 / M — Automatic Champion replacement
**What:** Promote a Challenger to Champion without human action when its
    evidence window is statistically dominant.
**Why:** Removes a manual step from the daily flow.
**Pros:** Less ceremony.
**Cons:** Removes the primary safety valve (human approval) that the v1
    protocol exists to provide. **Do not enable until shadow evidence
    survives multiple regime transitions successfully.**
**Depends on:** Multiple full forward observation windows, drift detection,
    rollback rehearsed, approval outcomes recorded (T9).
**Start:** Dry-run recommendation only; UI shows "would auto-replace if
    enabled" without acting; never silently.
**Source:** Plan section "Deferred to TODOS.md" (#6).

## What this file is NOT

- This is not a feature wishlist. Every entry here is blocked by evidence
  the v1 plan must collect first.
- Adding an item here requires ownership of its prerequisite dependencies.
- Items here must not be picked up before their `Depends on:` rows close.

## Provenance

Items #1-#6 entered this list during the 2026-07-24 CEO review as
`Proposed TODOS.md Entries`; D16 added #3 (CSI300 / index_kline) after
the 2026-07-25 Eng review surfaced it. Total: 7 deferred items.
