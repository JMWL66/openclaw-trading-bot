"""
OKX Agent Trade Kit — Dual-mode client.
Tries the official @okx_ai/okx-trade-cli first (required for OKX AI Trading Competition).
Falls back to native OKX REST API v5 if the CLI is not installed.
"""
from __future__ import annotations

import base64
import datetime
import hmac
import json
import logging
import os
import shutil
import subprocess
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ──────────────── Auto-detect CLI availability ────────────────
_CLI_AVAILABLE: bool | None = None


def _check_cli() -> bool:
    """Check once whether `okx` CLI is on PATH."""
    global _CLI_AVAILABLE
    if _CLI_AVAILABLE is None:
        _CLI_AVAILABLE = shutil.which("okx") is not None
        if _CLI_AVAILABLE:
            logger.info("OKX CLI detected — using @okx_ai/okx-trade-cli (competition mode)")
        else:
            if os.environ.get("OKX_COMPETITION_MODE") == "1":
                logger.error("FATAL: OKX Competition Mode is ENABLED, but okx CLI is not found! "
                             "Please install it via `npm install -g @okx_ai/okx-trade-cli` or Disable Competition Mode in Settings. Exiting engine...")
                import sys
                sys.exit(1)
            else:
                logger.info("OKX CLI not found — using REST API fallback")
    return _CLI_AVAILABLE


# ══════════════════════════════════════════════════════════════
#  Mode A: CLI wrapper  (competition-compliant)
# ══════════════════════════════════════════════════════════════

def _run_cli(args: list[str], timeout: int = 30) -> dict | list | None:
    cmd = ["okx"] + args + ["--json"]
    logger.info(f"CLI exec: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"CLI error (rc={result.returncode}): {result.stderr.strip()}")
            if result.stdout.strip():
                logger.error(f"  stdout: {result.stdout.strip()[:500]}")
            # Still try to parse stdout for error details
            stdout = result.stdout.strip()
            if stdout:
                for i, ch in enumerate(stdout):
                    if ch in ("{", "["):
                        try:
                            parsed = json.loads(stdout[i:])
                            # Return error info for better diagnostics
                            if isinstance(parsed, list) and parsed:
                                err_msg = parsed[0].get("sMsg", "")
                                logger.error(f"  OKX error: {err_msg}")
                            return None
                        except json.JSONDecodeError:
                            pass
            return None
        stdout = result.stdout.strip()
        if not stdout:
            return None
        for i, ch in enumerate(stdout):
            if ch in ("{", "["):
                return json.loads(stdout[i:])
        return None
    except subprocess.TimeoutExpired:
        logger.error(f"CLI timed out: {' '.join(cmd)}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"CLI JSON parse error: {e}")
        return None
    except FileNotFoundError:
        logger.error("CLI binary 'okx' not found on PATH")
        return None


# ══════════════════════════════════════════════════════════════
#  Mode B: REST API  (fallback)
# ══════════════════════════════════════════════════════════════

BASE_URL = "https://www.okx.com"


def _iso_time() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _auth_headers(method: str, request_path: str, body: str = "") -> dict:
    api_key = os.environ.get("OKX_API_KEY", "")
    secret_key = os.environ.get("OKX_SECRET_KEY", "")
    passphrase = os.environ.get("OKX_PASSPHRASE", "")
    is_demo = os.environ.get("OKX_DEMO", "") == "1"

    ts = _iso_time()
    msg = ts + method.upper() + request_path + body
    sign = base64.b64encode(
        hmac.new(secret_key.encode(), msg.encode(), "sha256").digest()
    ).decode()

    headers = {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Accept": "application/json",
    }
    if is_demo:
        headers["x-simulated-trading"] = "1"
    return headers


def _parse(resp: requests.Response) -> dict | list | None:
    try:
        data = resp.json()
        if data.get("code") != "0":
            logger.error(f"REST API error: {data}")
            return data if "msg" in data else None
        return data.get("data", [])
    except Exception as e:
        logger.error(f"REST JSON parse error: {e}")
        return None


def _rest_get(path: str, auth: bool = False) -> dict | list | None:
    headers = _auth_headers("GET", path) if auth else {}
    return _parse(requests.get(BASE_URL + path, headers=headers, timeout=10))


def _rest_post(path: str, payload: dict) -> dict | list | None:
    body = json.dumps(payload)
    headers = _auth_headers("POST", path, body)
    return _parse(requests.post(BASE_URL + path, headers=headers, data=body, timeout=10))


# ══════════════════════════════════════════════════════════════
#  Public API  (auto-switches between CLI / REST)
# ══════════════════════════════════════════════════════════════

def get_ticker(inst_id: str) -> dict | None:
    if _check_cli():
        data = _run_cli(["market", "ticker", inst_id])
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return None
    # REST
    data = _rest_get(f"/api/v5/market/ticker?instId={inst_id}")
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_balance(ccy: str = "USDT") -> dict | None:
    if _check_cli():
        data = _run_cli(["account", "balance", "--ccy", ccy])
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            return data[0]
        return None
    # REST
    data = _rest_get(f"/api/v5/account/balance?ccy={ccy}", auth=True)
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_positions(inst_type: str = "SWAP") -> list:
    if _check_cli():
        data = _run_cli(["account", "positions", "--instType", inst_type])
        return data if isinstance(data, list) else []
    # REST
    data = _rest_get(f"/api/v5/account/positions?instType={inst_type}", auth=True)
    return data if isinstance(data, list) else []


def set_leverage(inst_id: str, lever: int, margin_mode: str = "cross") -> dict | None:
    if _check_cli():
        return _run_cli([
            "swap", "set-leverage",
            "--instId", inst_id,
            "--lever", str(lever),
            "--mgnMode", margin_mode,
        ])
    # REST
    data = _rest_post("/api/v5/account/set-leverage", {
        "instId": inst_id, "lever": str(lever), "mgnMode": margin_mode,
    })
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else None


def place_order(
    inst_id: str,
    side: str,
    ord_type: str,
    sz: str,
    px: str | None = None,
    td_mode: str = "cross",
    pos_side: str | None = None,
    sl_trigger_px: str | None = None,
    sl_ord_px: str | None = None,
    tp_trigger_px: str | None = None,
    tp_ord_px: str | None = None,
) -> dict | None:
    if _check_cli():
        args = [
            "swap", "place",
            "--instId", inst_id,
            "--side", side,
            "--ordType", ord_type,
            "--sz", str(sz),
            "--tdMode", td_mode,
        ]
        if px:
            args += ["--px", str(px)]
        if pos_side:
            args += ["--posSide", pos_side]
        if sl_trigger_px:
            args += ["--slTriggerPx", str(sl_trigger_px)]
            args += ["--slOrdPx", str(sl_ord_px) if sl_ord_px else "-1"]
        if tp_trigger_px:
            args += ["--tpTriggerPx", str(tp_trigger_px)]
            args += ["--tpOrdPx", str(tp_ord_px) if tp_ord_px else "-1"]
        return _run_cli(args)
    # REST
    payload: dict[str, Any] = {
        "instId": inst_id, "tdMode": td_mode, "side": side,
        "ordType": ord_type, "sz": str(sz),
    }
    if px:
        payload["px"] = str(px)
    if pos_side:
        payload["posSide"] = pos_side
    if sl_trigger_px or tp_trigger_px:
        algo: dict[str, str] = {}
        if sl_trigger_px:
            algo["slTriggerPx"] = str(sl_trigger_px)
            algo["slOrdPx"] = str(sl_ord_px) if sl_ord_px else "-1"
        if tp_trigger_px:
            algo["tpTriggerPx"] = str(tp_trigger_px)
            algo["tpOrdPx"] = str(tp_ord_px) if tp_ord_px else "-1"
        payload["attachAlgoOrds"] = [algo]
    data = _rest_post("/api/v5/trade/order", payload)
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else {"error": "order failed"}


def place_algo_order(
    inst_id: str,
    side: str,
    sz: str,
    tp_trigger_px: str | None = None,
    sl_trigger_px: str | None = None,
    td_mode: str = "cross",
) -> dict | None:
    """Place a conditional (algo) stop-loss / take-profit order."""
    if _check_cli():
        args = [
            "swap", "place-algo-order",
            "--instId", inst_id,
            "--side", side,
            "--ordType", "conditional",
            "--sz", str(sz),
            "--tdMode", td_mode,
        ]
        if sl_trigger_px:
            args += ["--slTriggerPx", str(sl_trigger_px)]
            args += ["--slOrdPx", "-1"]
        if tp_trigger_px:
            args += ["--tpTriggerPx", str(tp_trigger_px)]
            args += ["--tpOrdPx", "-1"]
        return _run_cli(args)
    # REST
    payload: dict[str, Any] = {
        "instId": inst_id,
        "tdMode": td_mode,
        "side": side,
        "ordType": "conditional",
        "sz": str(sz),
    }
    if sl_trigger_px:
        payload["slTriggerPx"] = str(sl_trigger_px)
        payload["slOrdPx"] = "-1"
    if tp_trigger_px:
        payload["tpTriggerPx"] = str(tp_trigger_px)
        payload["tpOrdPx"] = "-1"
    data = _rest_post("/api/v5/trade/order-algo", payload)
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else None


def close_position(inst_id: str, margin_mode: str = "cross") -> dict | None:
    if _check_cli():
        return _run_cli([
            "swap", "close", "--instId", inst_id, "--mgnMode", margin_mode,
        ])
    # REST
    data = _rest_post("/api/v5/trade/close-position", {
        "instId": inst_id, "mgnMode": margin_mode,
    })
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else None


# ──────────────── Extended Market Data ────────────────

def get_candles(inst_id: str, bar: str = "1H", limit: int = 20) -> list:
    """Fetch K-line / candlestick data.
    bar options: 1m, 5m, 15m, 30m, 1H, 2H, 4H, 1D, etc.
    Returns list of [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm].
    """
    if _check_cli():
        data = _run_cli(["market", "candles", inst_id, "--bar", bar, "--limit", str(limit)])
        return data if isinstance(data, list) else []
    # REST — public, no auth needed
    data = _rest_get(f"/api/v5/market/candles?instId={inst_id}&bar={bar}&limit={limit}")
    return data if isinstance(data, list) else []


def get_funding_rate(inst_id: str) -> dict | None:
    """Fetch current funding rate for a SWAP instrument."""
    if _check_cli():
        data = _run_cli(["market", "funding-rate", inst_id])
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            return data[0]
        return None
    # REST — public
    data = _rest_get(f"/api/v5/public/funding-rate?instId={inst_id}")
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_open_interest(inst_id: str) -> dict | None:
    """Fetch open interest for a SWAP instrument."""
    if _check_cli():
        data = _run_cli(["market", "open-interest", "--instType", "SWAP", "--instId", inst_id])
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data:
            return data[0]
        return None
    # REST — public
    data = _rest_get(f"/api/v5/public/open-interest?instType=SWAP&instId={inst_id}")
    if isinstance(data, list) and data:
        return data[0]
    return None


# ──────────────── Technical Indicators ────────────────

def compute_rsi(candles: list, period: int = 14) -> float | None:
    """Compute RSI from candle data. Candles are [ts, o, h, l, c, vol, ...].
    Returns RSI value (0-100) or None if insufficient data.
    """
    if len(candles) < period + 1:
        return None
    # Extract close prices (index 4), candles are newest-first from OKX
    closes = [float(c[4]) for c in reversed(candles) if isinstance(c, list) and len(c) >= 5]
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Smoothed RSI (Wilder's method)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


# ──────────────── Hot-list Scanner ────────────────

# Tokens excluded from dynamic hot-list (majors + stables)
_EXCLUDE_BASE = {
    "BTC", "ETH", "USDC", "DAI", "TUSD", "FDUSD", "USDT",
    "BUSD", "EUR", "GBP", "BNB",
}


def get_all_swap_tickers(quote_ccy: str = "USDT") -> list:
    """Return all live USDT-margined SWAP tickers from OKX (public endpoint)."""
    if _check_cli():
        # @okx_ai/okx-trade-cli v1.3.0 expects instType as a positional arg.
        data = _run_cli(["market", "tickers", "SWAP"])
        if isinstance(data, list):
            return [t for t in data
                    if str(t.get("instId", "")).endswith(f"-{quote_ccy}-SWAP")]
    # REST fallback (always available, no auth needed)
    data = _rest_get(f"/api/v5/market/tickers?instType=SWAP")
    if isinstance(data, list):
        return [t for t in data
                if str(t.get("instId", "")).endswith(f"-{quote_ccy}-SWAP")]
    return []


def get_top_gainers(
    min_vol_usdt: float = 20_000_000,
    min_gain_pct: float = 10.0,
    max_gain_pct: float = 200.0,
    top_n: int = 10,
) -> list:
    """
    Scan all USDT SWAP tickers and return inst_ids of top N 24h gainers.

    Filters applied:
      - 24h USDT volume >= min_vol_usdt  (liquidity gate)
      - 24h gain in [min_gain_pct, max_gain_pct]  (momentum gate, avoids blow-off tops)
      - Excludes BTC, ETH, stablecoins

    Returns list of inst_id strings e.g. ["ORDI-USDT-SWAP", "1000SATS-USDT-SWAP", ...]
    """
    tickers = get_all_swap_tickers()
    if not tickers:
        logger.warning("get_top_gainers: received no tickers")
        return []

    candidates: list[tuple[float, float, str]] = []
    for t in tickers:
        inst_id: str = t.get("instId", "")
        base = inst_id.split("-")[0]
        if base in _EXCLUDE_BASE:
            continue
        try:
            last      = float(t.get("last",       0) or 0)
            open24h   = float(t.get("open24h",    0) or 0)
            vol_usdt  = float(t.get("volCcy24h",  0) or 0)  # already in USDT
        except (ValueError, TypeError):
            continue

        if last <= 0 or open24h <= 0 or vol_usdt < min_vol_usdt:
            continue

        gain_pct = (last - open24h) / open24h * 100.0
        if not (min_gain_pct <= gain_pct <= max_gain_pct):
            continue

        candidates.append((gain_pct, vol_usdt, inst_id))

    # Sort: highest gain first; break ties by volume
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    result = [c[2] for c in candidates[:top_n]]
    logger.info(f"Top gainers ({len(result)}): "
                + ", ".join(f"{c[2]}(+{c[0]:.1f}%)" for c in candidates[:top_n]))
    return result


# ──────────────── Helpers ────────────────

def normalize_inst_id(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if symbol.endswith("-SWAP"):
        return symbol
    if symbol.endswith("-USDT"):
        return f"{symbol}-SWAP"
    for suffix in ("USDT", "USD", "/USDT", "/USD"):
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
            break
    return f"{symbol}-USDT-SWAP"


def get_market_summary(instruments: list[str]) -> dict[str, Any]:
    """Fetch comprehensive market data for all instruments.
    Includes: ticker, 1H & 4H candles, funding rate, open interest.
    """
    summary: dict[str, Any] = {}
    for inst in instruments:
        inst_id = normalize_inst_id(inst)
        ticker = get_ticker(inst_id)
        if not ticker:
            continue

        entry: dict[str, Any] = {"ticker": ticker, "inst_id": inst_id}

        # K-line data (1H latest 24 bars, 4H latest 12 bars) — enough for RSI(14)
        try:
            entry["candles_1h"] = get_candles(inst_id, bar="1H", limit=24)
        except Exception:
            entry["candles_1h"] = []
        try:
            entry["candles_4h"] = get_candles(inst_id, bar="4H", limit=12)
        except Exception:
            entry["candles_4h"] = []

        # Pre-compute RSI
        entry["rsi_1h"] = compute_rsi(entry.get("candles_1h", []), period=14)
        entry["rsi_4h"] = compute_rsi(entry.get("candles_4h", []), period=14)

        # Funding rate
        try:
            entry["funding_rate"] = get_funding_rate(inst_id)
        except Exception:
            entry["funding_rate"] = None

        # Open interest
        try:
            entry["open_interest"] = get_open_interest(inst_id)
        except Exception:
            entry["open_interest"] = None

        summary[inst_id] = entry
    return summary
