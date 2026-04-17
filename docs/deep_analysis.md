# 🔬 OpenClaw 交易系统深度分析报告

---

## 一、为什么 `size` 必须转为整数？

### 直接原因：OKX 合约的计量单位

OKX USDT 本位永续合约的最小交易单位是**"张"（contracts）**，必须是正整数：

| 标的 | 每张合约面值 | 最小下单量 |
|------|------------|-----------|
| BTC-USDT-SWAP | 0.01 BTC | 1 张 |
| ETH-USDT-SWAP | 0.1 ETH | 1 张 |
| SOL-USDT-SWAP | 1 SOL | 1 张 |

传 `size=0.1` 或 `size=0.01` 给 OKX 会直接报错。

### 实际发生了什么？

虽然 SKILL.md 最后一行明确写了：
> `size` 必须是整数张数 (contracts)... 禁止输出带小数点的 size！

但 **MiniMax AI 依然输出了小数**。这是因为：

1. AI 的推理过程是"15% 净值 ÷ 杠杆 ÷ 合约面值"，算出来往往不是整数
2. AI 优先关注数学计算的"精确性"，忽略了格式约束
3. 仅靠 prompt 要求"禁止小数"不可靠 — **需要代码层做兜底**

### 你真正需要的是什么？

**不是强制把 0.1 转成 1 — 而是让 AI 正确计算张数**。

当前问题在于 AI 输出的 `size` 含义混乱：
- 有时候 `size=0.01` 表示 0.01 BTC（即 1 张 BTC 合约）
- 有时候 `size=0.3` 表示 0.3 ETH（即 3 张 ETH 合约）
- 有时候 `size=0.1` 是想表达"很小的仓位"

正确做法是**两层防御**：

```python
# 在 _validate_decision 中：
# 1. 如果 size < 1，说明 AI 可能输出的是"币数"而非"张数"，需要转换
# 2. 最终 size 必须 max(1, int(round(size)))
```

> [!IMPORTANT]
> 不建议仅在 SKILL.md 中写"禁止小数"，因为 LLM 会忽略。**必须在代码中加防御层。**

---

## 二、当前 SKILL.md 与官方规范的对比审查

### 官方规范要求 vs 当前 SKILL 对比

| 审核标准 | 要求 | 当前 SKILL 状态 | 判定 |
|---------|------|----------------|------|
| AI 推理判断步骤 | 须包含 AI 综合决策环节 | ✅ Step 3 有详细的条件检查和分级逻辑 | ✅ 合格 |
| 通过 Agent Trade Kit 下单 | 仅 ATK 订单计入 | ⚠️ SKILL 中未提及 `tag = "agentTradeKit"` | ❌ 不合格 |
| 明确止损与风控规则 | 仓位上限、止损条件清晰 | ✅ Step 5 有止盈止损，风控铁律 5 条 | ✅ 合格 |
| AI 参与度高 | 推理步骤越丰富越好 | ✅ 多层次推理（RSI/K线/OI/费率/背离） | ✅ 优秀 |
| 多信号融合 | 技术面+资金费率+持仓量 | ✅ 5 个维度综合判断 | ✅ 优秀 |
| 自适应逻辑 | 根据市场状态动态调整 | ✅ 比赛阶段自适应（初期/中期/后期） | ✅ 优秀 |
| 实盘数据佐证 | 有真实交易记录 | ❌ 跑了 3 天无成交 | ❌ 缺失 |

### 🔴 5 个不符合规范的关键问题

#### 问题 1：缺失 `tag = "agentTradeKit"`（致命‼️）

> [!CAUTION]
> **活动规则第 3 条**："仅限经由 Agent Trade Kit 自动执行的 USDT 永续合约计入"
> **Skill 规范示例**：`tag = "agentTradeKit" - 必填，否则不计入排行榜`

当前状态：
- SKILL.md 中**未提及 tag 字段**
- `okx_client.py` 的 `place_order()` 函数**没有 tag 参数**
- 从测试日志看，CLI 返回的 `"tag": "CLI"` — 这是 CLI 默认值

**影响**：即使交易成功，也可能不计入排行榜！

> 不过根据 CLI 帮助信息，通过 `okx swap place` 下的单会自动带上 `tag`，需要确认 CLI 是否已内置 `agentTradeKit` tag。从测试返回的 `"tag": "CLI"` 来看，应该是 OK 的（CLI 工具本身就代表 Agent Trade Kit）。但仍应在 SKILL.md 中明确声明。

#### 问题 2：SKILL 格式不符合规范模板

规范要求类似以下结构面：
```
# Step 4 · 执行下单
调用 swap_place_order：
instId = ...
side = ...
tag = "agentTradeKit"
```

当前 SKILL 的 Step 4 写的是 JSON 格式的"行动与仓位管理"，没有按规范格式写明具体调用哪些 API 函数。

#### 问题 3：SKILL 缺少明确的 API 调用声明

规范示例明确列出了每一步调用的 API：
- `market_get_candles`
- `market_get_funding_rate`  
- `market_get_open_interest`
- `swap_place_order`
- `swap_place_algo_order`

当前 SKILL 只说"你会收到以下数据"，没有声明调用了哪些 API，这可能影响评审得分。

#### 问题 4：执行节奏"每 60 秒"不合理

规范示例是"每 4 小时触发一次"，你的另一个策略文件 `docs/策略` 写的是"每 1 小时"。

当前 SKILL 写"每轮扫描间隔约 60 秒"：
- ✅ 扫描频率高有利于捕捉短期信号
- ❌ 但 1H K线数据每小时才更新一次，60 秒扫描其实在看同样的数据
- ❌ AI 推理开销大（每次要调 MiniMax API + 大量 K线数据）

#### 问题 5：止损应使用独立的 algo order

规范 Step 5 明确写：
> 开仓后立即调用 **swap_place_algo_order** 设置止损

当前代码是在 `swap place`（主订单）中附加 TP/SL（`--tpTriggerPx` / `--slTriggerPx`），这**不是独立的 algo order**。虽然也能生效，但与规范示例不一致。

---

## 三、活动规则分析 — 赢得比赛需要什么？

### 关键规则解读

| 规则 | 要点 | 当前状态 |
|------|------|---------|
| 比赛时间 | 04/09 17:00 ~ 04/23 17:00 (14天) | 已过 4 天，剩余 10 天 |
| 上榜门槛① | 交易账户总资产 ≥ 500 USDT | ✅ 已满足 (~500 USDT) |
| 上榜门槛② | 累计成交额 ≥ 1,000 USDT | ❌ **几乎为 0** |
| 收益率排名 | 净盈亏 / 最大净投入 × 100% | 当前 0% |
| 收益额排名 | AI 交易净盈亏 (含浮动盈亏) | 当前 ~0 |
| Skill 提交 | 截止 04/30 17:00 | 未提交 |

### 🚨 最紧迫的问题

> [!WARNING]
> **成交额为 0，连上榜门槛（≥1000 USDT）都没达到！**

要激活上榜资格，需要至少 1000 USDT 的累计成交额。按 ETH 当前价格：
- 1 张 ETH 合约 ≈ 220 USDT 名义价值
- 开仓 + 平仓 = 2×220 = 440 USDT 成交额
- **至少需要做 3 笔完整的开平仓才能达到 1000 USDT 门槛**

### 奖项结构

1. **收益率榜** — 适合小资金，ROI 高即可
2. **收益额榜** — 适合大资金，绝对利润
3. **Skill 精选奖** — 策略质量评审

以 500 USDT 的账户，冲**收益率榜**和**Skill 精选奖**是最现实的路径。

---

## 四、完整改进方案

### 🔧 A. 代码层修复（立即执行）

#### A1. Size 整数化防御

在 [ai_trader.py](file:///Users/jiamiweilai/Desktop/openclaw-trading-bot/src/ai_trader.py) 的 `execute_decision` 中：

```python
# 当前代码
sz=str(decision.get("size", 1))

# 改为
raw_size = decision.get("size", 1)
sz = str(max(1, int(round(float(raw_size)))))
```

同时在 `minimax_engine.py` 的 `_validate_decision` 中也加一层：

```python
# 当前
"size": float(decision.get("size", 0)),

# 改为
"size": max(1, int(round(float(decision.get("size", 1))))),
```

#### A2. `<think>` 标签解析（672 次出现！）

MiniMax M2.5 会输出 `<think>...</think>` 包裹的推理内容，然后才是 JSON。

当前的 `_parse_decision` 没有处理 `<think>` 标签，导致它在 `content` 中搜索 `{` 时，可能找到 think 块里的无效 JSON。

修复：
```python
# 在 _parse_decision 最前面加：
import re
content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
```

#### A3. 增加 K线数据量

当前只拉 6 根 K线，RSI(14) 根本算不出来。AI 自己也多次抱怨"数据不足以计算 RSI"。

在 [okx_client.py](file:///Users/jiamiweilai/Desktop/openclaw-trading-bot/src/okx_client.py) 的 `get_market_summary` 中：

```python
# 当前
entry["candles_1h"] = get_candles(inst_id, bar="1H", limit=6)
entry["candles_4h"] = get_candles(inst_id, bar="4H", limit=6)

# 改为 — 给 AI 足够数据计算 RSI(14)
entry["candles_1h"] = get_candles(inst_id, bar="1H", limit=24)
entry["candles_4h"] = get_candles(inst_id, bar="4H", limit=12)
```

#### A4. 代码层面预计算 RSI

不要让 AI"心算" RSI，在代码中预计算好再传给 AI，准确性大幅提升。

### 🧠 B. 策略层调整

#### B1. 降低入场门槛

当前的门槛导致 99% 的时间 HOLD。修改建议：

| 参数 | 当前值 | 建议值 | 理由 |
|------|--------|--------|------|
| RSI 超卖阈值 | < 30 | < 40 | 30 太极端，正常市场很少触发 |
| RSI 超买阈值 | > 70 | > 60 | 同上 |
| 最低开仓条件数 | ≥ 2 个 | ≥ 1 个（初期）| 初期需要积累成交额 |
| confidence 下限 | 0.6 | 0.45 | 0.6 太高，B级边缘信号被过滤 |
| "市场不明确选择 HOLD" | 存在 | 移除 | 这条让 AI 几乎永远 HOLD |
| "剧烈波动 > 3% 选 HOLD" | 存在 | 改为 > 5% | 3% 太敏感 |

#### B2. 调整执行节奏

```
当前：每 60-120 秒扫描一次（大部分时间看同样的 K线数据）
建议：每 15-30 分钟扫描一次
```

理由：
- 1H K线 60 分钟才更新一根，频繁扫描浪费 API 调用
- 减少 MiniMax API 费用
- 但也不能太慢，15-30 分钟是 sweet spot

#### B3. 比赛阶段自适应需要修正

当前比赛已经过了第 4 天（04/09 开始），但 AI 认为自己在"第 1 天"（因为它看的是引擎启动时间而非比赛开始时间）。

**需要在 prompt 中传入当前日期和比赛开始日期：**
```
比赛开始日期：2026-04-09
当前日期：2026-04-13
已过天数：4 天
剩余天数：10 天
当前阶段：中期阶段
```

### 📝 C. SKILL.md 重写建议

按规范模板重构，需要包含：

1. **策略名称** — 保留"威科夫背离策略"即可
2. **执行节奏** — 改为"每 15 分钟触发一次"
3. **Step 1** — 明确调用 `market_get_candles`，数据量增加到 24 根
4. **Step 2** — 明确调用 `market_get_funding_rate` + `market_get_open_interest`
5. **Step 3** — AI 综合判断，保留核心逻辑但**大幅降低门槛**
6. **Step 4** — 明确调用 `swap_place_order`，声明 `tag = "agentTradeKit"`
7. **Step 5** — 明确调用 `swap_place_algo_order` 设置止损
8. **风控规则** — 保留核心风控

### 🔌 D. 运维与稳定性

#### D1. 确保引擎 7×24 小时运行

```bash
# 使用 nohup + 监控脚本
nohup python3 src/ai_trader.py --trader_id trader_1775783420406 &

# 或使用 pmtool / launchd 做守护
```

#### D2. 防止 macOS 休眠关闭进程

```bash
caffeinate -i python3 src/ai_trader.py --trader_id trader_1775783420406
```

---

## 📊 优先级排序

| 优先级 | 任务 | 目的 | 预计影响 |
|--------|------|------|---------|
| 🔴 P0 | 修复 size 整数化 + `<think>` 解析 | 让交易能成功下单 | 从 0→有交易 |
| 🔴 P0 | 降低策略入场门槛 | 让 AI 能产生交易信号 | 成交额从 0→>1000 |
| 🔴 P0 | 确保引擎 24h 运行 | 不再长时间离线 | 从30%在线→99%在线 |
| 🟡 P1 | 增加 K线数据到 24 根 | 让 AI 能准确计算 RSI | 决策质量提升 |
| 🟡 P1 | 传入正确的比赛阶段 | AI 做出阶段性正确决策 | 策略执行正确 |
| 🟡 P1 | 代码预计算 RSI/EMA | 不再靠 AI 心算 | 信号准确率提升 |
| 🟢 P2 | 按规范模板重写 SKILL.md | 申请 Skill 精选奖 | 竞赛评审加分 |
| 🟢 P2 | 增加独立 algo order 止损 | 符合规范要求 | 风控更可靠 |

---

## 💬 关于你的问题

> "为什么要把 AI 返回的小数 size 强制转为整数？"

**不是"强制转"，而是"防御性兜底"。** LLM 不是确定性的程序，你无法保证它每次都遵守"输出整数张数"的指令。SKILL.md 里虽然写了，但 AI 在实际运行中明确违反了这条规则（7 次全是小数）。

正确的架构应该是：
1. **SKILL.md** 告诉 AI 要输出整数张数（尝试在 prompt 层引导）
2. **`_validate_decision()`** 在代码层做 `max(1, int(round(size)))` 兜底
3. **`execute_decision()`** 在执行前再检查一次

这样即使 AI 输出了 `size=0.1`（想表达 0.1 BTC = 10 张合约），也会被兜底为 `size=1`（最小 1 张）。虽然不完美，但至少**能成功下单而不是报错**。

需要我按上述方案立即修改代码吗？
