#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_OUTPUT_DIR = DATA_DIR / "exports"
TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export all local trade records into analysis-friendly CSV and JSON files."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for exported files (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def load_trade_files() -> list[Path]:
    files: list[Path] = []
    files.extend(sorted((DATA_DIR / "sessions").glob("*/trades.json")))
    files.extend(sorted((DATA_DIR / "history").rglob("trades.json")))
    return [path for path in files if path.is_file()]


def read_trade_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError(f"Expected a list in {path}, got {type(payload).__name__}")

    return [row for row in payload if isinstance(row, dict)]


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_number(value: float | None, digits: int = 8) -> str:
    if value is None:
        return ""
    text = f"{value:.{digits}f}"
    text = text.rstrip("0").rstrip(".")
    return text if text else "0"


def extract_asset(symbol: Any) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""

    for suffix in ("-USDT-SWAP", "-USDC-SWAP", "-USD-SWAP", "-USDT", "-USDC", "/USDT", "/USDC"):
        if suffix in text:
            return text.split(suffix)[0]

    for suffix in ("USDT", "USDC", "USD"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]

    for separator in ("-", "/"):
        if separator in text:
            return text.split(separator)[0]

    return text


def infer_trade_action(record: dict[str, Any]) -> str:
    trade_action = str(record.get("tradeAction") or "").strip().upper()
    if trade_action in {"OPEN", "CLOSE"}:
        return trade_action

    action = str(record.get("action") or "").strip().upper()
    if action.startswith("OPEN_"):
        return "OPEN"
    if action.startswith("CLOSE_"):
        return "CLOSE"

    direction = str(record.get("direction") or "").strip().lower()
    side = str(record.get("type") or "").strip().upper()
    if direction == "long":
        if side == "BUY":
            return "OPEN"
        if side == "SELL":
            return "CLOSE"
    if direction == "short":
        if side == "SELL":
            return "OPEN"
        if side == "BUY":
            return "CLOSE"

    return ""


def source_meta(path: Path) -> dict[str, str]:
    relative = path.relative_to(BASE_DIR)
    parts = relative.parts
    if len(parts) >= 4 and parts[0] == "data" and parts[1] == "sessions":
        return {
            "source_group": "live_session",
            "session_id": parts[2],
            "source_file": str(relative),
        }

    if len(parts) >= 4 and parts[0] == "data" and parts[1] == "history":
        return {
            "source_group": "history",
            "session_id": parts[-2],
            "source_file": str(relative),
        }

    return {
        "source_group": "unknown",
        "session_id": path.parent.name,
        "source_file": str(relative),
    }


def normalize_trade_record(path: Path, record: dict[str, Any], record_index: int) -> dict[str, Any]:
    meta = source_meta(path)
    time_text = str(record.get("time") or "").strip()
    parsed_time = parse_time(time_text)
    amount = safe_float(record.get("amount"))
    price = safe_float(record.get("price"))
    pnl = safe_float(record.get("pnl"))
    balance = safe_float(record.get("balance"))
    leverage = safe_float(record.get("leverage"))
    confidence = safe_float(record.get("confidence"))
    trade_action = infer_trade_action(record)
    error = str(record.get("error") or "").strip()
    status = "failed" if error else "recorded"
    symbol = str(record.get("symbol") or "").strip()

    normalized = {
        "record_index": record_index,
        "source_group": meta["source_group"],
        "session_id": meta["session_id"],
        "source_file": meta["source_file"],
        "id": str(record.get("id") or ""),
        "time": time_text,
        "time_iso": parsed_time.isoformat(sep=" ") if parsed_time else "",
        "asset": extract_asset(symbol),
        "symbol": symbol,
        "type": str(record.get("type") or "").strip().upper(),
        "action": str(record.get("action") or "").strip().upper(),
        "tradeAction": trade_action,
        "direction": str(record.get("direction") or "").strip().lower(),
        "amount": fmt_number(amount),
        "price": fmt_number(price),
        "leverage": fmt_number(leverage),
        "pnl": fmt_number(pnl, digits=4),
        "balance": fmt_number(balance, digits=4),
        "confidence": fmt_number(confidence, digits=4),
        "status": status,
        "error": error,
        "reason": str(record.get("reason") or "").strip(),
    }
    return normalized


def build_rows() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for path in load_trade_files():
        try:
            records = read_trade_rows(path)
        except ValueError as exc:
            warnings.append(str(exc))
            continue

        for index, record in enumerate(records, start=1):
            rows.append(normalize_trade_record(path, record, index))

    rows.sort(
        key=lambda row: (
            parse_time(row["time"]) or datetime.min,
            row["session_id"],
            row["source_file"],
            row["record_index"],
        )
    )
    return rows, warnings


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "record_index",
        "source_group",
        "session_id",
        "source_file",
        "id",
        "time",
        "time_iso",
        "asset",
        "symbol",
        "type",
        "action",
        "tradeAction",
        "direction",
        "amount",
        "price",
        "leverage",
        "pnl",
        "balance",
        "confidence",
        "status",
        "error",
        "reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_groups = Counter(row["source_group"] for row in rows)
    sessions = Counter(row["session_id"] for row in rows)
    assets = Counter(row["asset"] or "(unknown)" for row in rows)

    asset_stats: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "asset": "",
            "records": 0,
            "open_records": 0,
            "close_records": 0,
            "failed_records": 0,
            "pnl_sum": 0.0,
        }
    )
    session_stats: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "session_id": "",
            "source_group": "",
            "records": 0,
            "failed_records": 0,
            "pnl_sum": 0.0,
        }
    )

    for row in rows:
        asset = row["asset"] or "(unknown)"
        session_id = row["session_id"]
        pnl = safe_float(row["pnl"]) or 0.0

        asset_entry = asset_stats[asset]
        asset_entry["asset"] = asset
        asset_entry["records"] += 1
        asset_entry["pnl_sum"] += pnl
        if row["tradeAction"] == "OPEN":
            asset_entry["open_records"] += 1
        if row["tradeAction"] == "CLOSE":
            asset_entry["close_records"] += 1
        if row["status"] == "failed":
            asset_entry["failed_records"] += 1

        session_entry = session_stats[session_id]
        session_entry["session_id"] = session_id
        session_entry["source_group"] = row["source_group"]
        session_entry["records"] += 1
        session_entry["failed_records"] += 1 if row["status"] == "failed" else 0
        session_entry["pnl_sum"] += pnl

    time_values = [row["time"] for row in rows if row["time"]]
    return {
        "generated_at": generated_at,
        "base_dir": str(BASE_DIR),
        "records_exported": len(rows),
        "source_files": len(load_trade_files()),
        "source_groups": dict(source_groups),
        "sessions": dict(sessions),
        "assets": dict(assets),
        "time_range": {
            "start": time_values[0] if time_values else "",
            "end": time_values[-1] if time_values else "",
        },
        "notes": [
            "amount is exported as recorded in the source file; for swap records it may be contract size rather than quote turnover.",
            "live_session records come from local trades.json and may include failed order attempts plus pnl values that remain 0.",
        ],
        "warnings": warnings,
        "by_asset": sorted(
            (
                {
                    **entry,
                    "pnl_sum": round(float(entry["pnl_sum"]), 4),
                }
                for entry in asset_stats.values()
            ),
            key=lambda item: (-int(item["records"]), str(item["asset"])),
        ),
        "by_session": sorted(
            (
                {
                    **entry,
                    "pnl_sum": round(float(entry["pnl_sum"]), 4),
                }
                for entry in session_stats.values()
            ),
            key=lambda item: (-int(item["records"]), str(item["session_id"])),
        ),
    }


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows, warnings = build_rows()
    summary = summarize(rows, warnings)

    records_csv = output_dir / "all_trade_records.csv"
    records_json = output_dir / "all_trade_records.json"
    asset_csv = output_dir / "trade_summary_by_asset.csv"
    session_csv = output_dir / "trade_summary_by_session.csv"
    summary_json = output_dir / "trade_export_summary.json"

    write_csv(records_csv, rows)
    records_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary_csv(asset_csv, summary["by_asset"])
    write_summary_csv(session_csv, summary["by_session"])
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Exported {len(rows)} trade records")
    print(f"Records CSV: {records_csv}")
    print(f"Records JSON: {records_json}")
    print(f"Asset summary CSV: {asset_csv}")
    print(f"Session summary CSV: {session_csv}")
    print(f"Summary JSON: {summary_json}")
    if warnings:
        print(f"Warnings: {len(warnings)}")


if __name__ == "__main__":
    main()
