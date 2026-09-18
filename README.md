# CK Quant

**A privacy-first Freqtrade distribution with Web & Android remote management**

**[English](README.md) | [中文](README.zh-CN.md)**

[![GitHub Release](https://img.shields.io/github/v/release/ericchegncn/CK_Quant?display_name=tag)](https://github.com/ericchegncn/CK_Quant/releases/latest)
[![Docker Hub](https://img.shields.io/docker/v/ericchenghz/ck-quant?label=Docker%20Hub&sort=semver)](https://hub.docker.com/r/ericchenghz/ck-quant/tags)
[![Android APK](https://img.shields.io/badge/Android-APK-3DDC84?logo=android&logoColor=white)](https://github.com/ericchegncn/CK_Quant/releases/latest)

---

> ## 🔀 This is the **CK Quant Hedge** branch — dual-side (hedge mode) futures support
>
> It lets a strategy hold a **long and a short leg on the same pair at the same time**,
> which upstream freqtrade explicitly does not support.
>
> - Docker image: **`ericchenghz/ck-quant-hedge`**
> - Install, configuration and every hedge-mode parameter: **[docs/hedge-mode.md](docs/hedge-mode.md)**
> - This repository contains **framework capability only** — no private strategies, configs or
>   credentials. Enforced automatically by `.github/workflows/privacy-guard.yml` on every push.
> - `hedge_mode` defaults to **off**: with it off, the single-side code path is byte-identical to upstream.

---

## Quick start (hedge mode)

```bash
docker pull ericchenghz/ck-quant-hedge:latest
docker run -d --name ck-quant-hedge \
  -v "$(pwd)/user_data:/freqtrade/user_data" \
  -p 127.0.0.1:8080:8080 \
  ericchenghz/ck-quant-hedge:latest \
  trade --config /freqtrade/user_data/config.json
```

Three switches turn it on — `trading_mode: "futures"`, `margin_mode: "cross"` (or `isolated`),
`hedge_mode: true`. `max_open_trades` then counts **legs**, not pairs (one pair can hold two).

**Do not** work from guesswork: **[docs/hedge-mode.md](docs/hedge-mode.md)** covers installation
(Docker / docker-compose / source / APK), every hedge-mode parameter, the isolated-vs-cross
trade-off, runnable backtest commands, a 5-minute verification with the bundled demo strategy,
dry-run validation and a live-trading checklist — plus a troubleshooting table and the six
sharp edges that bite people (they are all handled in code, but you should know they exist).

---

## Features

| Feature | Description |
|---|---|
| **Dual-side positions (hedge mode)** | Hold a long **and** a short leg on the **same pair at the same time** — upstream freqtrade refuses this. Off by default; with it off the single-side path stays byte-identical. **[Guide →](docs/hedge-mode.md)** |
| **Crash-safe order recovery** | Restores exchange orders after rapid stop-and-reverse trading, preventing infinite restart loops |
| **Synthetic iceberg orders** | Optional split of large orders into hidden slices for entries and exits |
| **Card-based responsive UI** | Translucent, mobile-friendly WebUI with 7 locales (zh-CN, zh-TW, en, de, ja, fr, ko) |
| **Authenticated admin workspace** | Edit/validate config & strategy online, auto-backup, safe reload/restart |
| **Android app** | Connect to your server, manage bots, operate trades from your phone |
| **CK Quant Desktop** | Beginner-oriented Windows workspace with offline lifetime machine licensing, encrypted credentials, AI chat, serial backtests, deterministic G1-G10 gates, monitoring and confirmed paper deployment |
| **Tick-level backtest engine** | Memory-friendly engine matching exits on real tick sequences instead of guessing OHLCV bar paths |
| **Mark-to-market drawdown** | Equity drawdown combining realized and unrealized P&L |
| **Gainers/Losers pairlist** | Rank pairs by percent change (top gainers + top losers), mixable with volume/static lists |
| **Real-time profit factor** | Includes unrealized P&L of open trades — statistics never lag while the bot runs |
| **One-command release** | Build → push Docker Hub → tag → GitHub Release in one command |


---

## CK Quant Desktop

The Windows desktop app is under [`desktop/`](desktop/). It uses a one-time **10,000 USDT lifetime license** bound to a machine code; there is no recurring subscription. The customer app contains only the public verification key, while registration codes are signed in the separate, ignored manufacturer console.

The one-click research workflow starts from a 15m adaptation of Freqtrade's public `SampleStrategy`, never from a user's private strategy. Imported private strategies, generated variants, API credentials, backtest artifacts and audit data stay in the local application-data directory and are excluded from Git and release packages.

All backtests run serially through the local CK Quant Docker container. Missing statistical evidence is shown as **not evaluated**, and paper deployment requires an explicit user confirmation. Live capital activation remains a separate manual confirmation step.

See [`desktop/README.md`](desktop/README.md) for installation, activation and development details.

---

## Installation (Docker)

**Prerequisites**: Docker with Compose v2. No Python environment needed.

```bash
mkdir CK_Quant
cd CK_Quant

# Download the compose file
curl -L https://raw.githubusercontent.com/ericchegncn/CK_Quant/main/docker-compose.yml \
  -o docker-compose.yml

# Pull the image and create your user directory
docker compose pull
docker compose run --rm CK_Quant create-userdir --userdir user_data
> The compose service runs with `working_dir: /CK_Quant`, so relative
> paths like `user_data` land inside the mounted volume.
> (Absolute path also works: `--userdir /CK_Quant/user_data`)


# Generate a starter config
docker compose run --rm CK_Quant new-config --config user_data/config.json
```

**Image selection**:

| Image | Use case |
|---|---|
| `ericchenghz/ck-quant:stable` | Standard trading (recommended) |
| `ericchenghz/ck-quant:stable-freqai` | FreqAI models (LightGBM/XGBoost/RF) |
| `ericchenghz/ck-quant:stable-freqai-rl` | FreqAI + PyTorch reinforcement learning |

Set `CK_QUANT_IMAGE` in `.env` to switch.

### First-time configuration

After `new-config`, edit `user_data/config.json` to set the essentials:

```jsonc
{
    "exchange": {
        "name": "binance",
        "key": "YOUR_API_KEY",       // from the exchange (enable futures trading)
        "secret": "YOUR_API_SECRET", // keep it secret — it never enters the image
        "pair_whitelist": ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    },
    "stake_amount": 100,             // fixed amount per trade
    "max_open_trades": 5,
    "dry_run": true                  // start in paper-trading mode!
}
```

> **Always start with `dry_run: true`** (paper trading). Only switch to
> `false` after you understand the bot's behavior and expected P&L.
> For futures, create API keys with **Enable Futures** checked.

### Put your strategy in and start

```bash
# 1. Copy your private strategy into user_data/strategies/
# 2. Copy .env.example to .env and set CK_QUANT_STRATEGY to your class name
cp .env.example .env
#    CK_QUANT_STRATEGY=YourStrategyName

# 3. Start
docker compose up -d
docker compose logs -f --tail 200
```

WebUI listens on <http://127.0.0.1:8080> by default (configurable via `CK_QUANT_WEBUI_BIND` / `CK_QUANT_WEBUI_PORT`).

Config, strategies, database, credentials, models and logs all live in the
local `user_data` directory — **nothing sensitive enters the image**.

> **Security**: Never expose the admin/API port to the public internet.
> Use an HTTPS reverse proxy or a trusted VPN, plus a strong unique password
> and JWT secret. Test against a `dry_run` instance first.

---

## Feature guides

### 1. Multilingual WebUI & Android app

The WebUI ships 7 locales and an authenticated admin workspace:

- Edit common or full config parameters with server-side validation before saving
- Edit strategy parameters or strategy files online
- Automatic config/strategy backups, safe reload or restart after saving
- View runtime status, manage orders and positions via the Freqtrade API
- Review the admin audit trail

Admin is **disabled by default**; enable it explicitly in `config.json`:

```json
"ck_quant_admin": {
  "enabled": true,
  "config_edit": true,
  "strategy_edit": true
}
```

**Android APK**: Download from
[GitHub Releases](https://github.com/ericchegncn/CK_Quant/releases/latest).
After install, enter your server address plus the `api_server` username/password.
Full setup, reverse-proxy and security notes:
[docs/ck_quant_mobile_admin.md](docs/ck_quant_mobile_admin.md).

### 2. Gainers/Losers pairlist (rank by percent change)

Select top gainers and top losers dynamically, with **two modes**:

- `filter` (default): native freqtrade chain — ranks within the upstream pairlist only
- `union`: selects from the whole market independently and **merges** with upstream
  (Volume + Gainers + Static can coexist)

```jsonc
"pairlists": [
    {
        "method": "VolumePairList",
        "number_assets": 20,
        "sort_key": "quoteVolume",
        "refresh_period": 300
    },
    {
        "method": "GainersLosersPairList",
        "gainers_count": 10,      // top 10 gainers
        "losers_count": 5,        // top 5 losers
        "direction": "both",      // both / gainers / losers
        "mode": "union",          // union (hybrid) or filter
        "refresh_period": 300
    }
]
```

Verify with:

```bash
docker compose run --rm CK_Quant test-pairlist \
    --userdir user_data --config user_data/config.json
```

Full reference: [docs/gainers-losers-pairlist.md](docs/gainers-losers-pairlist.md).

### 3. Tick-level backtest engine

Match exits on real tick sequences to fix OHLCV backtest accuracy:

```text
Within one 15m bar both stop-loss and take-profit are hit — which came first?
  OHLCV backtest: guesses (assumed path) → systematically optimistic ❌
  Tick backtest:  real tick sequence → exact ✅
```

Measured (ETH 2025-07, 0.5% stop): 7.1% of trades had their trigger order
misjudged, and the OHLCV net P&L direction was opposite to the real tick
result. Tighter stops → bigger error.

```bash
# Download tick data (binance.vision, weekly chunks)
python scripts/download_vision_chunked.py ETHUSDT 20250701 20250731 \
    user_data/data/binance/futures/trades_eth

# Run the tick backtest
python -m freqtrade.ck_quant.tick_backtest \
    --config user_data/config.json --strategy MyPrivateStrategy \
    --data-dir user_data/data/binance/futures/trades_eth \
    --timerange 20250701-20250731 --pair "ETH/USDT:USDT" \
    --stoploss 0.005 --takeprofit 0.005
```

Details: [docs/advanced-tick-backtest.md](docs/advanced-tick-backtest.md).

### 4. Synthetic iceberg orders

Split a large order into hidden slices; the exchange only ever sees one at a time:

```json
{
    "iceberg_orders": {
        "enabled": true,
        "entry": true,
        "exit": true,
        "visible_ratio": 0.1,
        "max_slices": 10,
        "replenish_interval": 5.0,
        "size_jitter": 0.0
    }
}
```

Details: [docs/advanced-iceberg.md](docs/advanced-iceberg.md).

### 5. One-command release

```bash
python scripts/release.py 2026.8          # build → push Docker Hub → tag → GitHub Release
python scripts/release.py 2026.8 --dry-run  # preview
```

---

## Backtesting

```bash
docker compose run --rm CK_Quant backtesting \
    --userdir user_data \
    --config user_data/config.json \
    --strategy YourStrategy \
    --timeframe 15m --timeframe-detail 1m \
    --timerange 20260101-20260801 \
    --fee 0.001
```

> Use `--timeframe-detail 1m` for reliable results — pure 15m backtests are
> systematically optimistic (measured 12× overstatement on a large sample).

---

## Freqtrade upstream

[![Freqtrade CI](https://github.com/freqtrade/freqtrade/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/freqtrade/freqtrade/actions/workflows/ci.yml)
[![DOI](https://joss.theoj.org/papers/10.21105/joss.04864/status.svg)](https://doi.org/10.21105/joss.04864)
[![codecov](https://codecov.io/gh/freqtrade/freqtrade/branch/develop/graph/badge.svg?token=AD5BG3ATKI)](https://codecov.io/gh/freqtrade/freqtrade)
[![Documentation](https://readthedocs.org/projects/freqtrade/badge/)](https://www.freqtrade.io)
[![Discord Server](https://img.shields.io/badge/Freqtrade_Discord-4E4E4E?logo=discord)](https://discord.gg/p7nuUNVfP7)

Freqtrade is a free and open source crypto trading bot written in Python.
It is designed to support all major exchanges and be controlled via Telegram
or webUI. It contains backtesting, plotting and money management tools as
well as strategy optimization by machine learning.

This project is derived from Freqtrade and remains GPL-3.0 licensed. See
[CK_QUANT.md](CK_QUANT.md) for architecture notes.

## Disclaimer

This software is for educational purposes only. Do not risk money which
you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS
AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.

Always start by running a trading bot in Dry-Run and do not engage money
before you understand how it works and what profit/loss you should
expect.

We strongly recommend you to have coding and Python knowledge. Do not
hesitate to read the source code and understand the mechanism of this bot.

---

## License

GPL-3.0 — see [LICENSE](LICENSE).
