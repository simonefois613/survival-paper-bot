# Polymarket Survival Bot — PAPER MODE

A research bot inspired by the architecture visible in the supplied "Grok Bot / Survival Mode"
video. It is deliberately **paper-only**: it never contains a private key or live-order code.

The target experiment is:

- virtual starting bankroll: $100
- scan live Polymarket market metadata
- obtain live CLOB prices
- generate signals from market structure and price history
- size positions with capped fractional Kelly
- simulate fills, fees/slippage and mark-to-market
- persist every decision
- run every 10 minutes
- produce a machine-readable ledger for later analysis

## Important

This is an experiment, not evidence that the strategy is profitable. Prediction-market prices are
not guaranteed to provide exploitable edge. The bot must be evaluated on a forward sample before
any real-money deployment is considered.

## Architecture

Gamma API -> market discovery
CLOB API  -> price/orderbook/history
Strategy  -> signal + fair probability
Risk      -> fractional Kelly + hard limits
Paper     -> simulated execution
Ledger    -> JSON/CSV state
GitHub Actions -> scheduled execution

## Run locally

Python 3.11+:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python bot.py

The script creates `data/state.json`, `data/trades.csv`, and `data/signals.csv`.

## GitHub Actions

The included workflow runs every 10 minutes and commits the state/ledger back to the repository.
Create a repository, upload this folder, enable Actions, and make sure the workflow has
`contents: write` permission.

Scheduled GitHub Actions can be delayed; the timestamps in the ledger are authoritative.

## Strategy v0.2

This first forward-test version is intentionally conservative and transparent:

1. Discover active binary markets with enough liquidity/volume metadata.
2. Ignore markets too close to expiry or with insufficient displayed information.
3. Estimate a market-only fair probability using a blend of:
   - current midpoint;
   - recent price trend;
   - distance from recent mean;
   - volatility penalty.
4. Require a minimum model-vs-market edge.
5. Apply fractional Kelly, capped at 6% of bankroll per position.
6. Simulate execution at the displayed ask for buys and bid for sells, plus a configurable
   slippage buffer.
7. Never use more than the configured portfolio exposure.
8. Resolve positions from the market's final outcome when available; otherwise mark-to-market.

This is NOT the final strategy. The point of this run is to collect a clean forward dataset so
that strategy variants can be compared rather than selected from hindsight.

## Next iteration

After enough observations, add independent information sources (weather, sports/news, macro),
then compare them against the market-only baseline. A model that only looks profitable after
choosing parameters from the same forward sample is rejected as overfit.


## What is intentionally NOT copied from the video

The supplied video claims an agent scans 500–1000 markets every 10 minutes, derives fair value
from external information, uses a >8% edge gate, and caps Kelly sizing at 6% of bankroll.
Those claims are not independently verified by the video.

This prototype reproduces the *testable architecture* (scan cadence, edge gate, Kelly cap,
paper execution, persistent ledger), but its first fair-value model is deliberately simpler.
That prevents us from pretending that a profitable-looking result came from an unverified
claim or from hindsight.

The next upgrade is an independent-information layer (news/weather/sports/macroeconomic data)
and an LLM risk desk. Those will be added only after the baseline has a clean forward ledger.
