#!/usr/bin/env python3
"""
生成策略状态信息，用于前端展示
每分钟调用更新
"""

import json
import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "status.json"
STRATEGY_V2_FILE = BASE_DIR / "strategy_v2.json"


def main():
    # 读取v2策略配置
    with open(STRATEGY_V2_FILE) as f:
        strategy_v2 = json.load(f)

    trading_coins = [str(coin).upper().replace("USDT", "") for coin in strategy_v2.get("coins", [])]
    
    # 读取现有status
    status = {}
    if STATUS_FILE.exists():
        with open(STATUS_FILE) as f:
            status = json.load(f)
    
    # 更新策略信息
    status["mode"] = "strategy-v2"
    status["watchlist"] = trading_coins
    status["strategy_v2"] = {
        "version": "趋势回调v2.0",
        "takeProfit": f"第一目标+{strategy_v2.get('takeProfit', {}).get('firstTargetPct', 0.04) * 100:.1f}%卖50%，第二目标+{strategy_v2.get('takeProfit', {}).get('secondTargetPct', 0.08) * 100:.1f}%全卖",
        "stopLoss": f"固定{strategy_v2.get('stopLoss', {}).get('fixedLossPct', 0.015) * 100:.1f}% + 结构保护",
        "leverage": f"低波动{strategy_v2.get('position', {}).get('leverageVolatilityLow', {}).get('leverage', 10)}x / 中波动{strategy_v2.get('position', {}).get('leverageVolatilityMid', {}).get('leverage', 7)}x / 高波动{strategy_v2.get('position', {}).get('leverageVolatilityHigh', {}).get('leverage', 5)}x",
        "positionSize": f"单笔{strategy_v2.get('position', {}).get('sizeMinFraction', 0.10) * 100:.0f}%-{strategy_v2.get('position', {}).get('sizeMaxFraction', 0.15) * 100:.0f}%仓位，最多{strategy_v2.get('position', {}).get('maxConcurrentPositions', 3)}持仓",
        "entryLogic": "MA趋势判断+4选3回调开仓",
        "coins": trading_coins,
        "topN": strategy_v2.get("topN", 10)
    }
    
    # 保存
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)
    
    print(f"策略状态已更新: {len(trading_coins)}个交易币种")


if __name__ == "__main__":
    main()
