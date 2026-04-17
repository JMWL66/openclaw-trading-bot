# Meme 币动量突破策略 V1.0（打法 A）

## 策略定位
Meme / 小市值合约的**趋势跟踪**策略：只做多、追强势、快进快出。不做均值回归，不做空，不抄底。核心逻辑是"已经启动的上涨趋势里再加一脚"。

## 执行节奏
每 3 分钟触发一次（meme 行情推进极快，15 分钟级别会错过突破点）

## 交易标的
系统 watchlist 配置（建议）：
- **主力池**: DOGE-USDT-SWAP、PEPE-USDT-SWAP、WIF-USDT-SWAP、BONK-USDT-SWAP、FLOKI-USDT-SWAP
- **替补池**: SHIB-USDT-SWAP、POPCAT-USDT-SWAP
- **禁区**: 24h 涨幅 > 200% 的、刚上架 < 7 天的、非 USDT 永续

---

## Step 1 · 数据采集（系统已预取）
AI 拿到的每个标的数据包含：
- ticker（last, high24h, low24h, vol24h, bidPx, askPx）
- candles_1h（最近 24 根 1H K 线，格式 [ts, o, h, l, c, vol, ...]）
- candles_4h（最近 12 根 4H K 线）
- rsi_1h、rsi_4h（系统预计算）
- funding_rate（fundingRate, nextFundingRate, nextFundingTime）
- open_interest（oi, oiCcy）

---

## Step 2 · 标的硬过滤（AI 必须先做这一步）

遍历 watchlist 每个标的，以下门槛**任一不满足则排除**：

### 2.1 流动性门槛
- `vol24h × last` ≥ **50,000,000 USDT**（24h 成交额 > 50M U）
- `open_interest.oiCcy × last` ≥ **10,000,000 USDT**（OI > 10M U）

### 2.2 拥挤度门槛
- `|fundingRate| < 0.005`（|FR| < 0.5% / 8h）
- FR > 0.005 → 多头拥挤，排除
- FR < -0.005 → 空头拥挤（可能反弹，但本策略只做多不参与），排除

### 2.3 极端波动门槛
- 24h 涨跌幅绝对值 `|(last - open24h) / open24h| < 0.80`（避免追 >80% 的末端顶）

### 2.4 数据完整性
- candles_1h 长度 ≥ 15、candles_4h 长度 ≥ 3、rsi_1h 和 rsi_4h 非 None
- 任一缺失 → 排除

**如果过滤后没有任何标的剩余 → 输出 HOLD，reasoning 说明"无候选标的"。**

---

## Step 3 · AI 综合判断（核心 — 动量突破分析）

对过滤后的候选池，AI 按以下规则逐一评估，选**得分最高的一个**作为交易目标。

### 3.1 评分维度（每个维度独立打分）

| 维度 | 满足条件 | 得分 |
|---|---|---|
| **C1 短期连阳** | 最近 3 根 1H K 线连续阳线（每根 close > open） | +2 |
| **C2 突破新高** | 最新 1H close > 之前 12 根 1H 的最高 close | +2 |
| **C3 4H 同向** | 4H RSI > 50 且最新 4H K 线 close > open | +1 |
| **C4 动量强度** | 24h 涨幅 ≥ +8% 或最近 3 根 1H 累计涨幅 ≥ +3% | +2 |
| **C5 RSI 强势但非透支** | 1H RSI ∈ [60, 82] | +2 |
| **C6 成交量放大** | 最近一根 1H vol > 前 3 根 1H vol 均值 × 1.3 | +1 |
| **C7 FR 偏低** | `|fundingRate| < 0.003`（更严） | +1 |

### 3.2 信号分级与行动

| 总得分 | 级别 | action | confidence | 仓位比例 |
|---|---|---|---|---|
| ≥ 9 分 且 C1+C2+C4 全部满足 | **A 级** | OPEN_LONG | 0.80–0.92 | 账户净值 × 20% |
| 6–8 分 且 C1 或 C2 满足 | **B 级** | OPEN_LONG | 0.60–0.74 | 账户净值 × 12% |
| < 6 分 或 C1 和 C2 都不满足 | 弱 | HOLD | < 0.60 | — |

### 3.3 排除规则（即便分数够也一律 HOLD）

- 1H RSI > **85**（严重过热）→ HOLD
- 1H RSI < **50**（趋势未确立）→ HOLD
- 4H RSI < 45（大级别不同向）→ HOLD
- 距下次资金费率结算 < **20 分钟** → HOLD（避免被狙击）
- 最近一根 1H K 线有长上影线（上影 > 实体 × 2 且实体为阳）→ HOLD（衰竭信号）

### 3.4 不做空原则
**本策略只输出 OPEN_LONG / CLOSE_LONG / HOLD。** 绝不输出 OPEN_SHORT 或 CLOSE_SHORT。即便看到强势下跌，也 HOLD。

### 3.5 持仓管理（已持有该标的多头仓位时）

若 `positions` 中已有该标的多头仓位，本轮决策优先考虑以下平仓条件：

- **CLOSE_LONG**（任一触发）：
  - 浮盈 / 保证金 ≥ +25%（接近 +8% TP，提前锁利）且最新 1H 转阴
  - 1H RSI 冲到 > 85
  - funding_rate 突然转为 > +0.5%（拥挤度爆发）
  - 浮亏 / 保证金 ≤ -15%（软止损，让交易所算法单做最后一道）
- **HOLD**：浮盈 0~+25% 且未触发上述条件
- **不加仓**：已有仓位时不要再开同标的同方向

---

## Step 4 · 执行下单

仅当 Step 3 判定为 A 级或 B 级 OPEN_LONG 信号时才下单。

### 4.1 仓位计算

```
notional_target = account.totalEq × position_pct   # A=0.20, B=0.12
notional_with_lever = notional_target × 5           # 5x 杠杆
# 每张合约面值 (ctVal) 查询自标的规格，若无可近似按 last × standard_lot
size_contracts = floor(notional_with_lever / (last_price × ctVal))
size = max(1, size_contracts)    # 至少 1 张
```

常见 meme 合约 ctVal 参考：
- DOGE-USDT-SWAP: 1 张 = 1000 DOGE
- PEPE-USDT-SWAP: 1 张 = 10,000,000 PEPE
- WIF-USDT-SWAP: 1 张 = 1 WIF
- BONK-USDT-SWAP: 1 张 = 10,000 BONK
- FLOKI-USDT-SWAP: 1 张 = 10,000 FLOKI
- SHIB-USDT-SWAP: 1 张 = 1,000,000 SHIB

### 4.2 下单参数

调用 `swap_place_order`：
- `instId` = Step 3 选定的标的
- `side` = "buy"
- `ordType` = "market"
- `sz` = 上述计算的整数张数（必须整数，最小 1）
- `tdMode` = "cross"
- `tag` = "agentTradeKit"（必填，否则不计入排行榜）

### 4.3 杠杆
统一 **5x**（`swap_set_leverage`，mgnMode=cross）

---

## Step 5 · 止盈止损设置

开仓成功后**立即**调用 `swap_place_algo_order`：

- **stop_loss（触发价）** = 开仓价 × **0.97**（−3%）
- **take_profit（触发价）** = 开仓价 × **1.08**（+8%）

盈亏比设计：**1:2.67**（比主流币的 1:3 略低，因为 meme 波动大 −3% 比 −2% 更合理的容错）。

---

## 风控规则

1. **单笔最大亏损**：账户净值 20% × 3% = 0.6%（A 级）、12% × 3% = 0.36%（B 级），均远低于 2% 红线
2. **同时持仓上限**：**1 个标的**（meme 必须集中，不分散）
3. **日累计亏损**：账户净值 > **10%** 回撤 → 当日停止新开仓，只允许 CLOSE_LONG / HOLD
4. **连续 3 笔止损**（查 `trade_history` 最近 3 笔 pnl 为负）→ 2 小时内强制 HOLD
5. **信心度 < 0.60** → 必须 HOLD
6. **距资金费率结算 < 20 分钟** → 必须 HOLD
7. **禁止对冲**：同标的不允许同时持多空

---

## 特殊情况处理

- **市场闪崩**（单根 1H K 线跌幅 > -10%）：对所有持仓立即 CLOSE_LONG，后续 4 个周期 HOLD
- **数据不完整 / RSI/OI/FR 为 null**：该标的跳过筛选
- **所有标的被筛掉**：输出 HOLD，reasoning 说明

---

## 响应格式（严格遵守）

```json
{
  "action": "OPEN_LONG" | "CLOSE_LONG" | "HOLD",
  "instrument": "DOGE-USDT-SWAP",
  "size": 3,
  "leverage": 5,
  "reasoning": "筛选阶段：DOGE 通过（vol 89M U，OI 12M U，FR 0.08%）、PEPE 排除（vol 不足）。DOGE 1H RSI 72、3 连阳累涨 4.1%、24h +12%、vol 放大 1.6x、4H RSI 58 同向，C1+C2+C4+C5+C6+C7 合计 10 分 → A 级。账户 485u × 20% × 5x = 485u 名义价值，485/0.105/1000 ≈ 4.6 → 取 5 张。止损 0.1019，止盈 0.1134。",
  "confidence": 0.85,
  "stop_loss": 0.1019,
  "take_profit": 0.1134
}
```

**字段规则**：
- 本策略**绝不**输出 OPEN_SHORT / CLOSE_SHORT
- `size` 必须是**正整数**，OKX 要求整数张数
- `stop_loss` / `take_profit` 为**触发价格**（非订单价）
- `leverage` 统一 5
- `reasoning` 必须中文，且要体现 Step 2 筛选过程 + Step 3 打分过程
- 只输出 JSON，不要输出 markdown 或 `<think>` 标签
