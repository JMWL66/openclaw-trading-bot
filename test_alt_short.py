#!/usr/bin/env python3
"""
做空策略 Dry-Run 测试
=====================
- 扫描 OKX 24h 涨幅榜（真实数据）
- 拉取候选标的的全量市场数据
- 将数据 + SKILL_ALT_SHORT 发给 MiniMax AI
- 打印 AI 决策（不下单）

用法:  python test_alt_short.py
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

# 让 import 找到 src 目录
SRC_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_DIR))

import okx_client
from minimax_engine import MiniMaxEngine

# ─── 常量 ───
BASE_DIR = Path(__file__).resolve().parent
SKILL_FILE = BASE_DIR / "docs" / "SKILL_ALT_SHORT.md"
CONFIG_FILE = BASE_DIR / "data" / "system_config.json"

DIVIDER = "=" * 72


def load_api_key() -> str:
    """从 system_config.json 或环境变量获取 MiniMax API Key."""
    if os.environ.get("MINIMAX_API_KEY"):
        return os.environ["MINIMAX_API_KEY"]
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for prov in cfg.get("ai_providers", {}).values():
            if prov.get("type") == "minimax" and prov.get("api_key"):
                return prov["api_key"]
    print("❌  未找到 MINIMAX_API_KEY。请设置环境变量或检查 system_config.json")
    sys.exit(1)


def load_minimax_config() -> tuple[str, str]:
    """返回 (base_url, model)."""
    base_url = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
    model = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for prov in cfg.get("ai_providers", {}).values():
            if prov.get("type") == "minimax":
                base_url = prov.get("base_url", base_url)
                model = prov.get("model", model)
                break
    return base_url, model


def main():
    print(DIVIDER)
    print("🧪  山寨币流动性枯竭做空策略 — Dry-Run 测试")
    print(DIVIDER)

    # 1. 加载 SKILL
    if not SKILL_FILE.exists():
        print(f"❌  SKILL 文件不存在: {SKILL_FILE}")
        sys.exit(1)
    skill_content = SKILL_FILE.read_text(encoding="utf-8")
    print(f"✅  加载 SKILL: {SKILL_FILE.name} ({len(skill_content)} 字节)")

    # 2. 扫描热榜
    print("\n📡  正在扫描 OKX 24h 涨幅榜...")
    gainers = okx_client.get_top_gainers(
        min_vol_usdt=20_000_000,
        min_gain_pct=10.0,
        max_gain_pct=200.0,
        top_n=3,
    )
    if not gainers:
        print("⚠️  热榜扫描无结果（可能当前没有符合条件的标的）")
        print("    退出测试。")
        return

    print(f"🔥  候选标的 ({len(gainers)} 个):")
    for i, g in enumerate(gainers, 1):
        print(f"    {i}. {g}")

    # 3. 拉取市场数据（含 BTC 宏观）
    print("\n📊  拉取候选标的市场数据...")
    watchlist = gainers.copy()
    if "BTC-USDT-SWAP" not in watchlist:
        watchlist.insert(0, "BTC-USDT-SWAP")
    market_data = okx_client.get_market_summary(watchlist)
    print(f"✅  已获取 {len(market_data)} 个标的的数据")

    # 打印每个标的的关键指标
    print(f"\n{'标的':<20} {'最新价':>12} {'24h涨幅':>10} {'RSI(1H)':>10} {'资金费率':>12}")
    print("-" * 72)
    for inst_id, data in market_data.items():
        ticker = data.get("ticker", {})
        last = ticker.get("last", "N/A")
        open24h = ticker.get("open24h", "0")
        try:
            gain_pct = (float(last) - float(open24h)) / float(open24h) * 100
            gain_str = f"+{gain_pct:.1f}%" if gain_pct > 0 else f"{gain_pct:.1f}%"
        except (ValueError, ZeroDivisionError):
            gain_str = "N/A"
        rsi = data.get("rsi_1h")
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        fr = data.get("funding_rate", {})
        fr_str = fr.get("fundingRate", "N/A") if fr else "N/A"
        print(f"{inst_id:<20} {last:>12} {gain_str:>10} {rsi_str:>10} {fr_str:>12}")

    # 4. 模拟账户状态（不使用真实账户，避免误下单）
    mock_account = {
        "totalEq": "500.0",
        "availBal": "480.0",
        "details": [{"availBal": "480.0", "ccy": "USDT"}],
    }
    mock_positions: list = []
    mock_trades: list = []

    print(f"\n💰  模拟账户: 总权益 500 USDT, 可用 480 USDT, 无持仓")

    # 5. 发送给 MiniMax AI
    print(f"\n🤖  发送数据给 MiniMax AI 决策...")
    api_key = load_api_key()
    base_url, model = load_minimax_config()
    # 测试时强制使用标准模型（highspeed 在大输入时可能返回空）
    model = "MiniMax-M2.7"
    print(f"    模型: {model}")
    print(f"    Base URL: {base_url}")

    # 开启详细日志
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    engine = MiniMaxEngine(api_key=api_key, model=model, base_url=base_url)
    decision = engine.analyze_market(
        skill_content=skill_content,
        market_data=market_data,
        positions=mock_positions,
        account=mock_account,
        trade_history=mock_trades,
    )

    # 6. 展示结果
    print(f"\n{DIVIDER}")
    print("📋  AI 决策结果:")
    print(DIVIDER)
    print(f"  动作       : {decision.get('action', 'N/A')}")
    print(f"  标的       : {decision.get('instrument', 'N/A')}")
    print(f"  数量(张)   : {decision.get('size', 'N/A')}")
    print(f"  杠杆       : {decision.get('leverage', 'N/A')}x")
    print(f"  信心度     : {decision.get('confidence', 'N/A')}")
    print(f"  止损       : {decision.get('stop_loss', 'N/A')}")
    print(f"  止盈       : {decision.get('take_profit', 'N/A')}")
    print(f"\n  推理过程:")
    reasoning = decision.get("reasoning", "无")
    # 自动换行以便阅读
    for line in textwrap.wrap(reasoning, width=68):
        print(f"    {line}")

    print(f"\n{DIVIDER}")

    # 验证合规性
    action = decision.get("action", "HOLD")
    issues = []
    if action.startswith("OPEN"):
        if "SHORT" not in action:
            issues.append("❌ 做空策略不应输出 OPEN_LONG！")
        if not isinstance(decision.get("size"), int) or decision["size"] < 1:
            issues.append(f"❌ size 必须是正整数，当前: {decision.get('size')}")
        if decision.get("leverage") not in (8, 10, None, 0):
            issues.append(f"⚠️ 杠杆应为 8 或 10，当前: {decision.get('leverage')}")
        if decision.get("stop_loss") is None:
            issues.append("❌ 缺少 stop_loss")
        if decision.get("take_profit") is None:
            issues.append("❌ 缺少 take_profit")
    elif action == "HOLD":
        pass  # HOLD 是合法的
    elif "LONG" in action:
        issues.append(f"❌ 做空策略不应输出 {action}！")

    if issues:
        print("⚠️  合规性检查发现问题:")
        for issue in issues:
            print(f"    {issue}")
    else:
        print("✅  合规性检查通过")

    print(f"\n🏁  测试完成（未执行任何实际交易）\n")


if __name__ == "__main__":
    main()
