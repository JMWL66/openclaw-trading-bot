#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
CURRENT_SESSION_FILE = BASE_DIR / "current_session.json"
FREQTRADE_STRATEGY_DIR = Path(
    os.getenv(
        "FREQTRADE_STRATEGY_DIR",
        str(BASE_DIR.parent / "freqtrade" / "user_data" / "strategies"),
    )
)

FREQTRADE_API = os.getenv("FREQTRADE_API", "http://127.0.0.1:8080").rstrip("/")
AUTH = (
    os.getenv("FREQTRADE_USERNAME", "freqtrade"),
    os.getenv("FREQTRADE_PASSWORD", "freqtrade"),
)
REQUEST_TIMEOUT = float(os.getenv("FREQTRADE_TIMEOUT", "5"))
DEFAULT_SESSION_ID = os.getenv("FREQTRADE_SESSION_ID", "freqtrade_live")
MAX_TRADES = int(os.getenv("FREQTRADE_MAX_TRADES", "200"))
MAX_EQUITY_HISTORY = int(os.getenv("FREQTRADE_MAX_EQUITY_HISTORY", "240"))
MAX_WATCHLIST = int(os.getenv("FREQTRADE_MAX_WATCHLIST", "12"))
EQUITY_SNAPSHOT_SECS = int(os.getenv("FREQTRADE_EQUITY_SNAPSHOT_SECS", "60"))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def api_request(method: str, endpoint: str, **kwargs: Any) -> Any:
    response = requests.request(
        method,
        f"{FREQTRADE_API}{endpoint}",
        auth=AUTH,
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def api_get(endpoint: str, **kwargs: Any) -> Any:
    return api_request("GET", endpoint, **kwargs)


def api_post(endpoint: str, payload: Any | None = None, **kwargs: Any) -> Any:
    if payload is not None:
        kwargs["json"] = payload
    return api_request("POST", endpoint, **kwargs)


def normalize_symbol(pair: str | None) -> str:
    raw = str(pair or "").upper()
    return raw.replace(":USDT", "").replace("/", "")


def symbol_to_coin(symbol: str | None) -> str:
    resolved = normalize_symbol(symbol)
    return resolved[:-4] if resolved.endswith("USDT") else resolved


def normalize_coin_list(values: list[str] | None) -> list[str]:
    coins: list[str] = []
    for value in values or []:
        coin = symbol_to_coin(value)
        if coin and coin not in coins:
            coins.append(coin)
    return coins


def trade_direction(trade: dict[str, Any]) -> str:
    return "short" if bool(trade.get("is_short")) else "long"


def entry_side(direction: str) -> str:
    return "SELL" if direction == "short" else "BUY"


def exit_side(direction: str) -> str:
    return "BUY" if direction == "short" else "SELL"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_percent(value: Any, digits: int = 1) -> str:
    percentage = abs(safe_float(value)) * 100
    text = f"{percentage:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text}%"


def format_roi_summary(minimal_roi: Any) -> str:
    if not isinstance(minimal_roi, dict) or not minimal_roi:
        return "--"

    points: list[tuple[float, str, float]] = []
    for minute_key, roi_value in minimal_roi.items():
        minute = safe_float(minute_key, float("inf"))
        points.append((minute, str(minute_key), safe_float(roi_value)))

    points.sort(key=lambda item: item[0])
    formatted: list[str] = []
    for _, minute_key, roi_value in points:
        pct = f"{roi_value * 100:.1f}".rstrip("0").rstrip(".")
        formatted.append(f"{minute_key}m {pct}%")
    return " / ".join(formatted)


def describe_strategy(strategy_name: str, config: dict[str, Any]) -> dict[str, str]:
    normalized_name = strategy_name.strip() or "Freqtrade"
    timeframe = str(config.get("timeframe") or "--")
    trading_mode = str(config.get("trading_mode") or "--")
    mode_label = "Futures" if trading_mode == "futures" else trading_mode.upper()
    description = {
        "name": normalized_name,
        "timeframe": timeframe,
        "modeLabel": mode_label,
        "direction": "双向" if bool(config.get("can_short")) else "只做多",
        "entryRule": "按策略信号入场",
        "exitRule": "按策略信号出场",
    }

    if normalized_name == "BTCRSIStrategy":
        description.update({
            "direction": "只做多",
            "entryRule": "RSI < 35 开多",
            "exitRule": "RSI > 65 平仓",
        })

    return description


def resolve_strategy_target_leverage(strategy_name: str) -> float | None:
    if not strategy_name:
        return None

    strategy_path = FREQTRADE_STRATEGY_DIR / f"{strategy_name}.py"
    try:
        source = strategy_path.read_text(encoding="utf-8")
    except Exception:
        return None

    match = re.search(
        r"^\s*target_leverage\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$",
        source,
        flags=re.MULTILINE,
    )
    if not match:
        return None
    return safe_float(match.group(1)) or None


def resolve_session() -> tuple[dict[str, Any], Path]:
    current_session = read_json(CURRENT_SESSION_FILE, {})
    current_id = str(current_session.get("id") or "")
    current_path = current_session.get("path")

    if current_id.startswith("freqtrade") and current_path:
        session_id = current_id
        session_dir = BASE_DIR / current_path
    else:
        session_id = DEFAULT_SESSION_ID
        session_dir = SESSIONS_DIR / session_id

    session_dir.mkdir(parents=True, exist_ok=True)

    existing_status = read_json(session_dir / "status.json", {})
    started_at = (
        current_session.get("started_at")
        or existing_status.get("session_started_at")
        or now_str()
    )
    start_balance = current_session.get("start_balance")
    if start_balance is None:
        start_balance = existing_status.get("start_balance")

    metadata = {
        "id": session_id,
        "path": str(session_dir.relative_to(BASE_DIR)),
        "started_at": started_at,
    }
    if start_balance is not None:
        metadata["start_balance"] = round(safe_float(start_balance), 4)

    write_json(CURRENT_SESSION_FILE, metadata)

    for filename, default_payload in (
        ("status.json", {}),
        ("trades.json", []),
        ("thinking.json", []),
    ):
        path = session_dir / filename
        if not path.exists():
            write_json(path, default_payload)

    return metadata, session_dir


def build_open_positions(status_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_positions: list[dict[str, Any]] = []
    for trade in status_trades:
        if not trade.get("is_open"):
            continue
        symbol = normalize_symbol(trade.get("pair"))
        direction = trade_direction(trade)
        open_positions.append({
            "symbol": symbol,
            "direction": direction,
            "entryPrice": round(safe_float(trade.get("open_rate")), 6),
            "price": round(safe_float(trade.get("open_rate")), 6),
            "markPrice": round(
                safe_float(trade.get("current_rate"), safe_float(trade.get("open_rate"))),
                6,
            ),
            "unrealizedProfit": round(safe_float(trade.get("profit_abs")), 4),
            "leverage": round(safe_float(trade.get("leverage"), 1), 2),
            "amount": round(abs(safe_float(trade.get("amount"))), 6),
        })
    return open_positions


def normalize_trade_history(
    closed_trades: list[dict[str, Any]],
    open_trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_open_ids: set[Any] = set()

    for trade in closed_trades + open_trades:
        trade_id = trade.get("trade_id")
        if trade_id is not None:
            if trade.get("is_open"):
                seen_open_ids.add(trade_id)
            elif trade_id in seen_open_ids:
                continue

        symbol = normalize_symbol(trade.get("pair"))
        direction = trade_direction(trade)
        leverage = round(safe_float(trade.get("leverage"), 1), 2)
        amount = round(abs(safe_float(trade.get("amount"))), 6)
        open_time = trade.get("open_date")
        close_time = trade.get("close_date")
        open_price = safe_float(trade.get("open_rate"))
        close_price = safe_float(
            trade.get("close_rate"),
            safe_float(trade.get("current_rate"), open_price),
        )

        if open_time:
            normalized.append({
                "id": trade_id,
                "time": open_time,
                "type": entry_side(direction),
                "symbol": symbol,
                "amount": amount,
                "price": round(open_price, 6),
                "pnl": 0,
                "reason": trade.get("enter_tag") or "Freqtrade entry",
                "balance": None,
                "leverage": leverage,
                "direction": direction,
                "tradeAction": "OPEN",
            })

        if close_time and not trade.get("is_open"):
            normalized.append({
                "id": trade_id,
                "time": close_time,
                "type": exit_side(direction),
                "symbol": symbol,
                "amount": amount,
                "price": round(close_price, 6),
                "pnl": round(safe_float(trade.get("profit_abs")), 4),
                "reason": trade.get("exit_reason") or "Freqtrade exit",
                "balance": None,
                "leverage": leverage,
                "direction": direction,
                "tradeAction": "CLOSE",
            })

    normalized.sort(
        key=lambda item: (
            str(item.get("time") or ""),
            0 if item.get("tradeAction") == "OPEN" else 1,
            safe_float(item.get("id")),
        )
    )
    return normalized[-MAX_TRADES:]


def build_watchlist(
    whitelist_pairs: list[str],
    status_trades: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    existing_status: dict[str, Any],
) -> list[str]:
    whitelist = normalize_coin_list(whitelist_pairs)
    if whitelist:
        return whitelist[:MAX_WATCHLIST]

    ordered: list[str] = []
    for trade in status_trades + closed_trades:
        coin = symbol_to_coin(trade.get("pair"))
        if coin and coin not in ordered:
            ordered.append(coin)

    if ordered:
        return ordered[:MAX_WATCHLIST]

    existing_watchlist = existing_status.get("watchlist")
    if isinstance(existing_watchlist, list) and existing_watchlist:
        return [str(item) for item in existing_watchlist[:MAX_WATCHLIST]]

    return ["BTC", "ETH", "SOL", "BNB"]


def build_thinking(
    config: dict[str, Any],
    status_trades: list[dict[str, Any]],
    equity: float,
    session_pnl: float,
) -> list[dict[str, str]]:
    now = now_str()
    messages = [
        (
            f"Freqtrade {config.get('runmode', 'unknown')} 在线，"
            f"策略 {config.get('strategy', '--')}，状态 {config.get('state', '--')}。"
        ),
        (
            f"当前权益 {equity:.2f} USDT，本轮收益 "
            f"{session_pnl:+.2f} USDT，"
            f"已开仓 {len(status_trades)} 笔。"
        ),
    ]

    if status_trades:
        for trade in status_trades[:4]:
            direction = "空单" if trade_direction(trade) == "short" else "多单"
            messages.append(
                f"{symbol_to_coin(trade.get('pair'))} {direction} 持仓中，"
                f"入场 {safe_float(trade.get('open_rate')):.2f}，"
                f"现价 {safe_float(trade.get('current_rate'), safe_float(trade.get('open_rate'))):.2f}，"
                f"浮盈 {safe_float(trade.get('profit_abs')):+.2f} USDT。"
            )
    else:
        messages.append("当前空仓，等待下一次入场信号。")

    return [{"time": now, "thought": message} for message in messages]


def compress_equity_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compressed: list[dict[str, Any]] = []
    last_time: datetime | None = None

    for point in history:
        point_time = parse_time(point.get("time"))
        if point_time is None:
            continue
        normalized_point = {
            "time": point_time.strftime("%Y-%m-%d %H:%M:%S"),
            "balance": round(safe_float(point.get("balance")), 4),
            "equity": round(safe_float(point.get("equity"), safe_float(point.get("balance"))), 4),
        }
        if last_time is not None and (point_time - last_time).total_seconds() < EQUITY_SNAPSHOT_SECS:
            compressed[-1] = normalized_point
        else:
            compressed.append(normalized_point)
        last_time = point_time

    return compressed[-MAX_EQUITY_HISTORY:]


def is_after_session_start(value: Any, session_start: datetime | None) -> bool:
    if session_start is None:
        return True

    timestamp = parse_time(value)
    if timestamp is None:
        return True

    return timestamp >= session_start


def sync() -> dict[str, Any]:
    session_meta, session_dir = resolve_session()
    existing_status = read_json(session_dir / "status.json", {})

    config = api_get("/api/v1/show_config")
    balance = api_get("/api/v1/balance")
    status_trades = api_get("/api/v1/status")
    trades_payload = api_get("/api/v1/trades", params={"limit": MAX_TRADES, "offset": 0})
    try:
        whitelist_payload = api_get("/api/v1/whitelist")
    except requests.RequestException:
        whitelist_payload = {}

    closed_trades = trades_payload.get("trades", []) if isinstance(trades_payload, dict) else []
    whitelist_pairs = (
        whitelist_payload.get("whitelist", [])
        if isinstance(whitelist_payload, dict)
        else []
    )
    session_start = parse_time(session_meta.get("started_at"))
    session_status_trades = [
        trade
        for trade in status_trades
        if is_after_session_start(trade.get("open_date"), session_start)
    ]
    session_closed_trades = [
        trade
        for trade in closed_trades
        if is_after_session_start(trade.get("open_date") or trade.get("close_date"), session_start)
    ]

    open_positions = build_open_positions(session_status_trades)
    normalized_trades = normalize_trade_history(session_closed_trades, session_status_trades)
    watchlist = build_watchlist(whitelist_pairs, status_trades, closed_trades, existing_status)

    total_unrealized = round(sum(safe_float(pos.get("unrealizedProfit")) for pos in open_positions), 4)
    total_equity = safe_float(balance.get("total_bot"), safe_float(balance.get("total")))
    if not total_equity:
        total_equity = safe_float(balance.get("value_bot"), safe_float(balance.get("value")))
    available_balance = 0.0
    currencies = balance.get("currencies")
    if isinstance(currencies, list) and currencies:
        available_balance = safe_float(currencies[0].get("free"))
    wallet_balance = round(total_equity - total_unrealized, 4)

    strategy_name = str(config.get("strategy") or "Freqtrade")
    strategy_version = str(config.get("version") or strategy_name)
    strategy_description = describe_strategy(strategy_name, config)
    target_leverage = resolve_strategy_target_leverage(strategy_name)
    leverage_values = [safe_float(pos.get("leverage"), 1) for pos in open_positions]
    leverage_text = (
        f"{target_leverage:g}x"
        if target_leverage
        else (
            f"{max(leverage_values):g}x"
            if leverage_values
            else f"{safe_float(config.get('leverage') or 1, 1):g}x"
        )
    )
    stoploss_text = format_percent(config.get("stoploss"))
    roi_text = format_roi_summary(config.get("minimal_roi"))
    max_open_trades = int(safe_float(config.get("max_open_trades")))
    risk_guard = f"止损 {stoploss_text} · 最多 {max_open_trades} 持仓"

    start_balance = round(safe_float(session_meta.get("start_balance")), 4)
    if start_balance <= 0:
        start_balance = round(total_equity, 4)
        session_meta["start_balance"] = start_balance
        write_json(CURRENT_SESSION_FILE, session_meta)

    session_total_pnl = round(total_equity - start_balance, 4)
    status_payload = existing_status if isinstance(existing_status, dict) else {}
    history = status_payload.get("equity_history", [])
    current_time = now_str()
    if not isinstance(history, list):
        history = []
    valid_history: list[dict[str, Any]] = []
    min_valid_balance = start_balance * 0.5 if start_balance else 0
    max_valid_balance = start_balance * 5 if start_balance else float("inf")
    for point in history:
        point_balance = safe_float(point.get("equity"), safe_float(point.get("balance")))
        if min_valid_balance <= point_balance <= max_valid_balance:
            valid_history.append(point)
    history = valid_history
    history.append({
        "time": current_time,
        "balance": wallet_balance,
        "equity": round(total_equity, 4),
    })
    history = compress_equity_history(history)

    top_trade = (
        session_status_trades[0]
        if session_status_trades
        else (session_closed_trades[-1] if session_closed_trades else None)
    )
    top_signal = {
        "symbol": normalize_symbol(top_trade.get("pair")) if top_trade else None,
        "direction": trade_direction(top_trade) if top_trade else None,
        "score": round(safe_float(top_trade.get("profit_pct")), 2) if top_trade else None,
    }

    event_lines = build_thinking(config, session_status_trades, total_equity, session_total_pnl)
    events = [item["thought"] for item in event_lines][-8:]

    status_payload.update({
        "session_id": session_meta["id"],
        "session_started_at": session_meta["started_at"],
        "last_run": current_time,
        "start_balance": start_balance,
        "balance": wallet_balance,
        "equity": round(total_equity, 4),
        "available": round(available_balance, 4),
        "unrealized_pnl": total_unrealized,
        "equity_history": history,
        "positions": len(open_positions),
        "open_positions": open_positions,
        "trades_count": len(normalized_trades),
        "mode": f"freqtrade-{config.get('runmode', 'unknown')}",
        "watchlist": watchlist,
        "top_signal": top_signal,
        "events": events,
        "pause_reason": None,
        "daily_stop_loss_streak": 0,
        "strategy_v2": {
            "version": strategy_version,
            "name": strategy_description["name"],
            "timeframe": strategy_description["timeframe"],
            "modeLabel": strategy_description["modeLabel"],
            "direction": strategy_description["direction"],
            "entryRule": strategy_description["entryRule"],
            "exitRule": strategy_description["exitRule"],
            "takeProfit": f"ROI {roi_text}",
            "stopLoss": stoploss_text,
            "leverage": leverage_text,
            "positionSize": f"{config.get('stake_amount', '--')} {config.get('stake_currency', 'USDT')} / 最多 {max_open_trades} 持仓",
            "entryLogic": f"{strategy_name} / {config.get('timeframe', '--')} / {config.get('trading_mode', '--')}",
            "riskGuard": risk_guard,
            "coins": watchlist,
            "topN": int(safe_float(config.get("max_open_trades"), len(watchlist) or 1)),
        },
        "source": "freqtrade_api",
    })

    write_json(session_dir / "status.json", status_payload)
    write_json(session_dir / "trades.json", normalized_trades)
    write_json(session_dir / "thinking.json", event_lines)

    return {
        "running": True,
        "source": "freqtrade_api",
        "session": session_meta,
        "config": config,
        "status": status_payload,
        "trades": normalized_trades,
        "thinking": event_lines,
    }


if __name__ == "__main__":
    result = sync()
    print(
        "Freqtrade sync ok:",
        f"strategy={result['config'].get('strategy')}",
        f"positions={result['status'].get('positions')}",
        f"equity={result['status'].get('equity')}",
    )
