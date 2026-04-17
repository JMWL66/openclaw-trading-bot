# OpenClaw Trading Bot 🤖

OpenClaw 是一个专为 OKX AI 交易比赛设计的轻量级、多实例 AI 交易引擎。它利用 MiniMax AI 模型自主进行交易决策，并通过 OKX 接口管理模拟或真实的交易订单。

系统提供了一个设计精美且实时的监控仪表盘，能够同时创建、管理并并行运行多个 AI 代理（交易员实例）。

## 📁 项目结构

```text
openclaw-trading-bot/
├── start.sh                      # 🚀 一键启动脚本（推荐使用）
├── src/                          # 后端核心逻辑
│   ├── server.py                 # 多交易员实例管理器与 API 代理服务器
│   ├── ai_trader.py              # 单个交易员代理的主交易循环脚本
│   ├── minimax_engine.py         # 封装 MiniMax API 请求，用于生成 AI 决策
│   └── okx_client.py             # OKX V5 REST API 客户端封装
├── public/                       # 前端仪表盘
│   ├── index.html                # 实时监控的 Web 界面
│   ├── css/style.css             # 样式表
│   └── js/app.js                 # 前端逻辑
├── data/                         # 应用状态与数据
│   ├── system_config.json        # 全局配置（AI 密钥、交易所密钥、交易员实例信息）
│   ├── sessions/                 # 每个交易员的运行时数据（状态、交易记录、AI 思考过程）
│   └── exports/                  # 导出的交易记录（CSV/JSON）
├── docs/                         # 文档与策略
│   ├── SKILL.md                  # 主策略提示词与风控规则（当前使用）
│   ├── SKILL_MEME_HOTLIST.md     # Meme 热点榜追踪策略
│   ├── SKILL_MEME_BREAKOUT_A.md  # Meme 突破 A 型策略
│   ├── deep_analysis.md          # 深度市场分析文档
│   ├── strategy_v2.json          # 策略参数配置草稿
│   ├── skill规范.md               # Skill 文件编写规范
│   ├── 活动规则.md                # OKX AI 竞赛活动规则
│   └── 策略.md                   # 策略设计笔记
└── scripts/                      # 实用工具脚本
    └── export_trade_records.py   # 交易记录导出工具
```

## 🚀 快速开始

### 方式一：一键启动（推荐）

```bash
bash start.sh
```

脚本将自动：检查 Python 3.9+ → 安装依赖 → 启动服务 → **自动打开浏览器**

---

### 方式二：手动启动

1. **安装依赖**
   ```bash
   pip install requests flask flask_cors
   ```

2. **启动服务器**
   ```bash
   python3 src/server.py
   ```

3. **访问监控面板**：[http://127.0.0.1:5000](http://127.0.0.1:5000)

---

4. **配置全局运行参数**
   使用前端 UI 面板（点击右上角 `管理` 或 `全局设置`）：
   - 配置你的 **OKX API 密钥**、Secret 以及 Passphrase（支持模拟/实盘模式）。
   - 配置你的 **MiniMax API 密钥** 以启用 AI 模型权限。

5. **启动 AI 交易员**
   - 在面板左侧点击"创建新建交易实例"，为其起个名字。
   - 分配它的扫描频率（秒），并绑定刚刚设置的 OKX 节点和 AI 服务商。
   - 保存后在列表中点击 **"▶ 启动"**，即可让专属的 AI Agent 跑起来。

## ⚙️ 架构说明

- **`server.py`**: 负责管理子进程的掌控者。当你在 UI 上启动某个 Agent 时，`server.py` 会对应拉起一个无挂靠的 `ai_trader.py` 子进程并在后台持续监控它。
- **`ai_trader.py`**: AI 交易员引擎的核心。它会根据设定的 `scan_frequency` 进行轮询，通过 `okx_client.py` 抓取市场行情与账户当前持仓，然后结合 `SKILL.md` 的风控规则，提交给 `minimax_engine.py` 进行思考。如果 AI 返回了 `OPEN_LONG` 或 `OPEN_SHORT` 指令，引擎将直接在 OKX 执行该下单操作。
- **`index.html`**: UI 仪表盘。它会自动轮询 `data/sessions/<trader_id>/` 目录下由活跃交易员不断生成的 `status.json`、`thinking.json` 和 `trades.json` 文件并进行响应式的图形化渲染。
