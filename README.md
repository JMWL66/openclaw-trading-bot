# OpenClaw Trading Bot 🤖

OpenClaw 是一个专为 OKX AI 交易比赛设计的轻量级、多实例 AI 交易引擎。它利用 MiniMax AI 模型自主进行交易决策，并通过 OKX 接口管理模拟或真实的交易订单。

系统提供了一个设计精美且实时的监控仪表盘，能够同时创建、管理并并行运行多个 AI 代理（交易员实例）。

## 📁 项目结构

项目已被整理为逻辑清晰的组件结构：

```text
openclaw-trading-bot/
├── src/                          # 后端核心逻辑
│   ├── server.py                 # 多交易员实例管理器与 API 代理服务器
│   ├── ai_trader.py              # 单个交易员代理的主交易循环脚本
│   ├── minimax_engine.py         # 封装 MiniMax API 请求，用于生成 AI 决策
│   └── okx_client.py             # OKX V5 REST API 客户端封装
├── public/                       # 前端仪表盘 
│   └── index.html                # 实时监控的 Web 界面
├── data/                         # 应用状态与数据
│   ├── system_config.json        # 全局配置（包括 AI 密钥、交易所密钥、交易员实例信息）
│   ├── sessions/                 # （目录）保存每个交易员的运行时数据（状态、交易记录、AI 思考过程）
│   └── ...                       # 其他运行时快照数据
├── docs/                         # 文档与规则
│   ├── SKILL.md                  # 默认的系统提示词与 AI 模型的技能风控规则
│   └── strategy_v2.json          # 旧版/草稿策略参数
└── scripts/                      # 独立实用脚本
    └── ...                       # 例如 Freqtrade 相关的交易对同步脚本
```

## 🚀 快速开始

1. **安装依赖**
   请确保你已经安装了 Python 3.9+ 以及所需的基础库（如 `requests`, `flask`, `flask_cors`）。
   ```bash
   pip install requests flask flask_cors
   ```

2. **启动仪表盘服务器**
   进入项目根目录并启动 Flask 服务：
   ```bash
   python3 src/server.py
   ```

3. **访问监控面板**
   打开浏览器并访问：
   [http://127.0.0.1:5000](http://127.0.0.1:5000)

4. **配置全局运行参数**
   使用前端 UI 面板（点击右上角 `管理` 或 `全局设置`）：
   - 配置你的 **OKX API 密钥**、Secret 以及 Passphrase（支持模拟/实盘模式）。
   - 配置你的 **MiniMax API 密钥** 以启用 AI 模型权限。

5. **启动 AI 交易员**
   - 在面板左侧点击“创建新建交易实例”，为其起个名字。
   - 分配它的扫描频率（秒），并绑定刚刚设置的 OKX 节点和 AI 服务商。
   - 保存后在列表中点击 **“▶ 启动”**，即可让专属的 AI Agent 跑起来。

## ⚙️ 架构说明

- **`server.py`**: 负责管理子进程的掌控者。当你在 UI 上启动某个 Agent 时，`server.py` 会对应拉起一个无挂靠的 `ai_trader.py` 子进程并在后台持续监控它。
- **`ai_trader.py`**: AI 交易员引擎的核心。它会根据设定的 `scan_frequency` 进行轮询，通过 `okx_client.py` 抓取市场行情与账户当前持仓，然后结合 `SKILL.md` 的风控规则，提交给 `minimax_engine.py` 进行思考。如果 AI 返回了 `OPEN_LONG` 或 `OPEN_SHORT` 指令，引擎将直接在 OKX 执行该下单操作。
- **`index.html`**: UI 仪表盘。它会自动轮询 `data/sessions/<trader_id>/` 目录下由活跃交易员不断生成的 `status.json`、`thinking.json` 和 `trades.json` 文件并进行响应式的图形化渲染。
