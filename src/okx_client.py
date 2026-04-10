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
    logger.debug(f"CLI: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            logger.error(f"CLI error (rc={result.returncode}): {result.stderr.strip()}")
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
        if sl_ord_px:
            args += ["--slOrdPx", str(sl_ord_px)]
        if tp_trigger_px:
            args += ["--tpTriggerPx", str(tp_trigger_px)]
        if tp_ord_px:
            args += ["--tpOrdPx", str(tp_ord_px)]
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

        # K-line data (1H latest 6 bars, 4H latest 6 bars)
        try:
            entry["candles_1h"] = get_candles(inst_id, bar="1H", limit=6)
        except Exception:
            entry["candles_1h"] = []
        try:
            entry["candles_4h"] = get_candles(inst_id, bar="4H", limit=6)
        except Exception:
            entry["candles_4h"] = []

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

