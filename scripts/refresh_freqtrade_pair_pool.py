#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

import sync_freqtrade_api


FREQTRADE_CONFIG_PATH = Path(
    os.getenv("FREQTRADE_CONFIG_PATH", "/Users/jiamiweilai/Desktop/freqtrade/config.json")
).expanduser()
BINANCE_FUTURES_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"
MAJOR_PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
MEME_BASES = {
    "DOGE",
    "SHIB",
    "PEPE",
    "1000PEPE",
    "WIF",
    "BONK",
    "1000BONK",
    "1000SHIB",
    "FLOKI",
    "1000FLOKI",
    "MEME",
    "BOME",
    "BRETT",
    "NEIRO",
    "MOG",
    "TURBO",
    "POPCAT",
    "PENGU",
    "ACT",
    "MOODENG",
    "PNUT",
    "GOAT",
    "BABYDOGE",
    "CHEEMS",
    "DOGS",
    "HIPPO",
}
TOP_MEME_COUNT = int(os.getenv("FREQTRADE_TOP_MEME_COUNT", "2"))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def pair_from_symbol(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return f"{base}/USDT:USDT"


def fetch_top_meme_pairs() -> list[str]:
    response = requests.get(BINANCE_FUTURES_24H, timeout=10)
    response.raise_for_status()
    tickers = response.json()

    ranked: list[tuple[float, str]] = []
    for ticker in tickers:
        symbol = str(ticker.get("symbol") or "").upper()
        if not symbol.endswith("USDT"):
            continue
        base = symbol[:-4]
        if base not in MEME_BASES:
            continue
        ranked.append((float(ticker.get("quoteVolume") or 0), symbol))

    ranked.sort(reverse=True)

    selected: list[str] = []
    for _, symbol in ranked:
        pair = pair_from_symbol(symbol)
        if pair in MAJOR_PAIRS or pair in selected:
            continue
        selected.append(pair)
        if len(selected) >= TOP_MEME_COUNT:
            break

    return selected


def update_pool() -> dict[str, Any]:
    config = read_json(FREQTRADE_CONFIG_PATH)
    exchange = config.setdefault("exchange", {})

    top_memes = fetch_top_meme_pairs()
    target_pairs = [*MAJOR_PAIRS, *top_memes]
    exchange["pair_whitelist"] = target_pairs

    pairlists = config.setdefault("pairlists", [])
    if not pairlists:
        pairlists.append({"method": "StaticPairList"})
    else:
        pairlists[0]["method"] = "StaticPairList"

    write_json(FREQTRADE_CONFIG_PATH, config)

    reload_result: dict[str, Any] | None = None
    reload_error: str | None = None
    try:
        reload_result = sync_freqtrade_api.api_post("/api/v1/reload_config")
    except Exception as exc:
        reload_error = str(exc)

    return {
        "config_path": str(FREQTRADE_CONFIG_PATH),
        "majors": MAJOR_PAIRS,
        "memes": top_memes,
        "target_pairs": target_pairs,
        "reload_result": reload_result,
        "reload_error": reload_error,
    }


if __name__ == "__main__":
    result = update_pool()
    print(json.dumps(result, ensure_ascii=False, indent=2))
