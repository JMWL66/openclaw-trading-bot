"""
MiniMax AI Decision Engine.
Uses OpenAI-compatible SDK to call MiniMax M2.7 for trade decisions.
"""
from __future__ import annotations


import json
import logging
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

DECISION_SCHEMA = """\
You must respond with ONLY a valid JSON object (no markdown, no code blocks).
The JSON must follow this exact schema:

{
  "action": "OPEN_LONG" | "OPEN_SHORT" | "CLOSE_LONG" | "CLOSE_SHORT" | "HOLD",
  "instrument": "BTC-USDT-SWAP",
  "size": 0.1,
  "leverage": 10,
  "reasoning": "Your detailed analysis and reasoning in Chinese",
  "confidence": 0.85,
  "stop_loss": 80000.0,
  "take_profit": 90000.0
}

Field rules:
- action: Required. HOLD means do nothing this cycle.
- instrument: Required for OPEN/CLOSE actions. OKX SWAP format.
- size: Required for OPEN actions. Number of contracts.
- leverage: Required for OPEN actions. Integer 1-125.
- reasoning: Required. Explain your analysis.
- confidence: Required. Float 0.0-1.0.
- stop_loss: Required for OPEN actions. Price level.
- take_profit: Required for OPEN actions. Price level.
"""

DEFAULT_HOLD = {
    "action": "HOLD",
    "instrument": None,
    "size": 0,
    "leverage": 0,
    "reasoning": "AI 决策解析失败，默认观望。",
    "confidence": 0.0,
    "stop_loss": None,
    "take_profit": None,
}


class MiniMaxEngine:
    def __init__(self, api_key: str, model: str = "MiniMax-M2.7",
                 base_url: str = "https://api.minimax.io/v1"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def analyze_market(
        self,
        skill_content: str,
        market_data: dict[str, Any],
        positions: list[dict],
        account: dict[str, Any],
        trade_history: list[dict],
    ) -> dict[str, Any]:
        """
        Send market data + SKILL instructions to MiniMax and return a structured trade decision.
        """
        system_prompt = self._build_system_prompt(skill_content)
        user_prompt = self._build_user_prompt(market_data, positions, account, trade_history)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=2000,
            )

            content = response.choices[0].message.content.strip()
            logger.info(f"MiniMax raw response: {content[:500]}")

            decision = self._parse_decision(content)
            return decision

        except Exception as e:
            logger.error(f"MiniMax API error: {e}")
            return {**DEFAULT_HOLD, "reasoning": f"MiniMax API 调用失败: {str(e)}"}

    def _build_system_prompt(self, skill_content: str) -> str:
        return f"""\
你是一个专业的 AI 加密货币交易 Agent，正在参加 OKX AI Trading Challenge 比赛。
你通过 OKX Agent Trade Kit 管理 USDT 本位永续合约交易。

## 你的交易策略 (SKILL)
{skill_content}

## 决策输出格式
{DECISION_SCHEMA}

## 重要规则
1. 每次只能输出一个交易决策
2. 必须严格遵循策略中的风控规则
3. 仓位管理必须合理，不要过度杠杆
4. 如果市场不明确，选择 HOLD 观望
5. 所有推理必须用中文
6. 只输出 JSON，不要输出其他内容
"""

    def _build_user_prompt(
        self,
        market_data: dict[str, Any],
        positions: list[dict],
        account: dict[str, Any],
        trade_history: list[dict],
    ) -> str:
        sections = ["## 当前市场数据"]
        for inst_id, data in market_data.items():
            ticker = data.get("ticker", {})
            sections.append(f"""
### {inst_id}
- 最新价: {ticker.get('last', 'N/A')}
- 24h涨跌: {ticker.get('lastPx', ticker.get('change24h', 'N/A'))}
- 24h最高: {ticker.get('high24h', 'N/A')}
- 24h最低: {ticker.get('low24h', 'N/A')}
- 24h成交量: {ticker.get('vol24h', 'N/A')}
- 买一价: {ticker.get('bidPx', 'N/A')}
- 卖一价: {ticker.get('askPx', 'N/A')}""")

            # K-line data (1H)
            candles_1h = data.get("candles_1h", [])
            if candles_1h:
                sections.append(f"\n#### {inst_id} 1H K线 (最近 {len(candles_1h)} 根)")
                sections.append("| 时间戳 | 开 | 高 | 低 | 收 | 成交量 |")
                sections.append("|--------|-----|-----|-----|-----|--------|")
                for c in candles_1h:
                    if isinstance(c, list) and len(c) >= 6:
                        sections.append(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} | {c[4]} | {c[5]} |")

            # K-line data (4H)
            candles_4h = data.get("candles_4h", [])
            if candles_4h:
                sections.append(f"\n#### {inst_id} 4H K线 (最近 {len(candles_4h)} 根)")
                sections.append("| 时间戳 | 开 | 高 | 低 | 收 | 成交量 |")
                sections.append("|--------|-----|-----|-----|-----|--------|")
                for c in candles_4h:
                    if isinstance(c, list) and len(c) >= 6:
                        sections.append(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} | {c[4]} | {c[5]} |")

            # Funding rate
            fr = data.get("funding_rate")
            if fr:
                sections.append(f"\n#### {inst_id} 资金费率")
                sections.append(f"- 当前费率: {fr.get('fundingRate', 'N/A')}")
                sections.append(f"- 下次费率: {fr.get('nextFundingRate', 'N/A')}")
                sections.append(f"- 下次结算时间: {fr.get('nextFundingTime', 'N/A')}")

            # Open interest
            oi = data.get("open_interest")
            if oi:
                sections.append(f"\n#### {inst_id} 持仓量 (OI)")
                sections.append(f"- 持仓量: {oi.get('oi', 'N/A')}")
                sections.append(f"- 持仓量币数: {oi.get('oiCcy', 'N/A')}")

        # Account info
        details = account.get("details", [])
        avail_bal = details[0].get("availBal", "N/A") if details else account.get("availBal", "N/A")
        sections.append(f"\n## 账户状态")
        sections.append(f"- 可用余额 (USDT): {avail_bal}")
        sections.append(f"- 总权益: {account.get('totalEq', 'N/A')}")
        sections.append(f"- 已用保证金: {account.get('imr', 'N/A')}")

        # Positions
        if positions:
            sections.append(f"\n## 当前持仓 ({len(positions)} 个)")
            for p in positions:
                sections.append(f"""
### {p.get('instId', 'N/A')}
- 方向: {'多' if p.get('posSide') == 'long' or float(p.get('pos', 0)) > 0 else '空'}
- 数量: {p.get('pos', 'N/A')}
- 开仓均价: {p.get('avgPx', 'N/A')}
- 未实现盈亏: {p.get('upl', 'N/A')} USDT
- 杠杆: {p.get('lever', 'N/A')}x
- 保证金: {p.get('margin', p.get('imr', 'N/A'))} USDT""")
        else:
            sections.append("\n## 当前持仓: 无")

        # Recent trades
        if trade_history:
            recent = trade_history[-5:]
            sections.append(f"\n## 最近交易 (最新 {len(recent)} 笔)")
            for t in recent:
                sections.append(f"- {t.get('time', 'N/A')} | {t.get('action', t.get('type', 'N/A'))} | "
                              f"{t.get('instrument', t.get('symbol', 'N/A'))} | "
                              f"PnL: {t.get('pnl', 'N/A')} USDT")

        sections.append("\n请根据以上数据和你的策略，给出本轮交易决策。")
        return "\n".join(sections)

    def _parse_decision(self, content: str) -> dict[str, Any]:
        """Parse the LLM response into a structured decision dict."""
        # Try direct JSON parse first
        try:
            decision = json.loads(content)
            return self._validate_decision(decision)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        for marker in ("```json", "```"):
            if marker in content:
                start = content.index(marker) + len(marker)
                end = content.index("```", start) if "```" in content[start:] else len(content)
                try:
                    decision = json.loads(content[start:end].strip())
                    return self._validate_decision(decision)
                except (json.JSONDecodeError, ValueError):
                    pass

        # Try to find JSON object in content
        brace_start = content.find("{")
        brace_end = content.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            try:
                decision = json.loads(content[brace_start:brace_end])
                return self._validate_decision(decision)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse MiniMax decision: {content[:300]}")
        return {**DEFAULT_HOLD, "reasoning": f"AI 输出解析失败。原始输出: {content[:200]}"}

    def _validate_decision(self, decision: dict) -> dict[str, Any]:
        """Validate and normalize a decision dict."""
        valid_actions = {"OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT", "HOLD"}
        action = decision.get("action", "HOLD").upper()
        if action not in valid_actions:
            action = "HOLD"

        result = {
            "action": action,
            "instrument": decision.get("instrument"),
            "size": float(decision.get("size", 0)),
            "leverage": int(decision.get("leverage", 10)),
            "reasoning": decision.get("reasoning", "无推理说明"),
            "confidence": min(1.0, max(0.0, float(decision.get("confidence", 0.5)))),
            "stop_loss": decision.get("stop_loss"),
            "take_profit": decision.get("take_profit"),
        }

        # Ensure required fields for OPEN actions
        if action.startswith("OPEN") and (not result["instrument"] or result["size"] <= 0):
            logger.warning("OPEN action missing instrument or size, falling back to HOLD")
            result["action"] = "HOLD"
            result["reasoning"] += " [自动降级为HOLD: 缺少必要参数]"

        return result
