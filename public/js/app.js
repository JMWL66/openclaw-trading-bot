let chart = null;
        let tradeSignature = '';
        let thoughtSignature = '';
        let tradePanelMode = 'position';
        let latestTrades = [];
        let latestStatus = null;
        let latestOpenPosition = null;
        let latestMarketState = null;
        let latestSession = null;
        const LOCAL_API_BASE = window.location.protocol === 'file:'
            ? 'http://127.0.0.1:5000'
            : window.location.origin;
        const SOURCE_UTC_OFFSET_HOURS = 9;
        const DISPLAY_TIMEZONE = 'Asia/Shanghai';
        const initialBalance = 0;
        const majorCoins = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'LINK', 'AVAX', 'LTC'];

        function formatSigned(value, digits = 2) {
            const safeValue = Number(value) || 0;
            return `${safeValue > 0 ? '+' : ''}${safeValue.toFixed(digits)}`;
        }

        function formatRuntime(diffMs) {
            if (diffMs < 0) return '--';
            const totalMinutes = Math.max(0, Math.floor(diffMs / 60000));
            const days = Math.floor(totalMinutes / 1440);
            const hours = Math.floor((totalMinutes % 1440) / 60);
            const minutes = totalMinutes % 60;

            if (days > 0) {
                return `${days}天 ${hours}小时`;
            }
            if (hours > 0) {
                return `${hours}小时 ${minutes}分钟`;
            }
            return `${minutes}分钟`;
        }

        function parseSourceTimestamp(value) {
            if (!value) return null;
            if (value instanceof Date) return value;
            const text = String(value).trim();
            const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/);
            if (match) {
                const [, year, month, day, hour, minute, second = '00'] = match;
                return new Date(Date.UTC(
                    Number(year),
                    Number(month) - 1,
                    Number(day),
                    Number(hour) - SOURCE_UTC_OFFSET_HOURS,
                    Number(minute),
                    Number(second)
                ));
            }

            const parsed = new Date(text);
            return Number.isNaN(parsed.getTime()) ? null : parsed;
        }

        function formatBeijingTime(value, options = {}) {
            const date = parseSourceTimestamp(value);
            if (!date || Number.isNaN(date.getTime())) return value || '--';
            return date.toLocaleString('zh-CN', {
                timeZone: DISPLAY_TIMEZONE,
                hour12: false,
                ...options
            });
        }

        function formatBeijingCompact(value) {
            return formatBeijingTime(value, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        function formatLastRun(value) {
            if (!value) return '--';
            return formatBeijingTime(value, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        }

        function formatChartTime(value) {
            if (!value) return '--';
            return formatBeijingTime(value, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        function updateMetric(id, value, tone) {
            const element = document.getElementById(id);
            element.className = `metric-value ${tone}`;
            if (
                ['currentBalance', 'positionPnl', 'totalPnl'].includes(id)
                && typeof value === 'string'
                && value.endsWith(' USDT')
            ) {
                const amount = value.slice(0, -5);
                element.classList.add('has-unit');
                element.innerHTML = `<span class="metric-main">${amount}</span><span class="metric-unit">USDT</span>`;
                return;
            }
            element.textContent = value;
        }

        function escapeHtml(value) {
            return String(value ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        async function fetchJson(url, options = {}) {
            const response = await fetch(url, { cache: 'no-store', ...options });
            if (!response.ok) {
                throw new Error(`${response.status} ${response.statusText}`);
            }
            return response.json();
        }



        function findOpenPosition(trades, status) {
            const statusPosition = Array.isArray(status?.open_positions) ? status.open_positions[0] : null;
            if (statusPosition) return statusPosition;
            if (!trades || trades.length === 0) return null;

            let openPosition = null;
            trades.forEach((trade) => {
                const action = trade.tradeAction || (
                    (trade.direction || 'long') === 'short'
                        ? (trade.type === 'SELL' ? 'OPEN' : 'CLOSE')
                        : (trade.type === 'BUY' ? 'OPEN' : 'CLOSE')
                );

                if (action === 'OPEN') {
                    openPosition = trade;
                }
                if (action === 'CLOSE') {
                    openPosition = null;
                }
            });

            return openPosition;
        }

        function findOpenTrade(trades) {
            if (!trades || trades.length === 0) return null;

            let openTrade = null;
            trades.forEach((trade) => {
                const action = trade.tradeAction || (
                    (trade.direction || 'long') === 'short'
                        ? (trade.type === 'SELL' ? 'OPEN' : 'CLOSE')
                        : (trade.type === 'BUY' ? 'OPEN' : 'CLOSE')
                );

                if (action === 'OPEN') {
                    openTrade = trade;
                }
                if (action === 'CLOSE') {
                    openTrade = null;
                }
            });

            return openTrade;
        }

        async function getMarketState(symbol, entryPrice, direction, amount) {
            // Normalize symbol to OKX instId format
            let instId = symbol || 'BTC-USDT-SWAP';
            if (!instId.includes('-')) {
                instId = instId.replace('USDT', '') + '-USDT-SWAP';
            }

            try {
                const response = await fetch(`https://www.okx.com/api/v5/market/ticker?instId=${instId}`, { cache: 'no-store' });
                const data = await response.json();
                const tickerData = data?.data?.[0];
                const currentPrice = Number(tickerData?.last) || 0;
                const qty = Number(amount) || 1;
                const basePnl = entryPrice ? (currentPrice - Number(entryPrice)) * qty : 0;
                const pnl = (direction || 'long') === 'short' ? -basePnl : basePnl;

                return { price: currentPrice, pnl };
            } catch (error) {
                return { price: Number(entryPrice) || 0, pnl: 0 };
            }
        }

        function resolveDisplayStrategy(status) {
            const strategy = status?.strategy_v2 || {};
            const version = String(strategy.version || '').toLowerCase();
            const fallbackEntryLogic = String(strategy.entryLogic || '');
            const fallbackParts = fallbackEntryLogic.split('/').map((item) => item.trim()).filter(Boolean);
            const fallbackName = fallbackParts[0] || '';
            const fallbackTimeframe = fallbackParts[1] || '';
            const fallbackMode = fallbackParts[2] || '';

            function compactTakeProfit(value) {
                const raw = String(value || '').replace(/\+/g, '').trim();
                if (!raw) return '--';
                if (raw.startsWith('ROI {')) {
                    try {
                        const roiConfig = JSON.parse(raw.slice(4));
                        const entries = Object.entries(roiConfig)
                            .sort((a, b) => Number(a[0]) - Number(b[0]))
                            .map(([minute, roi]) => `${minute}m ${(Number(roi) * 100).toFixed(1).replace(/\.0$/, '')}%`);
                        return entries.length ? `ROI ${entries.join(' / ')}` : '--';
                    } catch (error) {
                        return raw;
                    }
                }
                const text = raw;
                if (!text) return '--';
                return text
                    .replace('平50%移保本', '减半')
                    .replace('全平', '全平')
                    .replace(/\s+/g, ' ');
            }

            function compactStopLoss(value) {
                const text = String(value || '');
                if (!text) return '--';
                const match = text.match(/主流([\d.]+%)\s*\/\s*山寨([\d.]+%)/);
                if (match) return `${match[1]}-${match[2]}止损`;
                return text;
            }

            function compactLeverage(value) {
                const text = String(value || '');
                if (!text) return '--';
                const match = text.match(/主流(\d+(?:-\d+)?)x\/山寨(\d+(?:-\d+)?)x/);
                if (match) return `主流${match[1]}x / 山寨${match[2]}x`;
                return text;
            }

            function compactText(value, fallback = '--') {
                const text = String(value || '').replace(/\s+/g, ' ').trim();
                return text || fallback;
            }

            function fallbackEntryRule(name) {
                if (name === 'BTCRSIStrategy') return 'RSI < 35 开多';
                if (version.includes('live-simple')) return '回踩 / 突破';
                return '按策略信号入场';
            }

            function fallbackExitRule(name) {
                if (name === 'BTCRSIStrategy') return 'RSI > 65 平仓';
                return '按策略信号平仓';
            }

            const timeframeText = compactText(strategy.timeframe || fallbackTimeframe, '');
            const modeText = compactText(
                strategy.modeLabel || (fallbackMode ? (fallbackMode === 'futures' ? 'Futures' : fallbackMode) : ''),
                ''
            );
            const riskGuardText = compactText(strategy.riskGuard, compactText(strategy.stopLoss, '--')).replace(/\s*\/\s*/g, ' · ');
            const nameText = compactText(strategy.name || strategy.version || fallbackName || 'Freqtrade');
            const fallbackEntry = compactText(strategy.entryRule, fallbackEntryRule(nameText));
            const fallbackExit = compactText(strategy.exitRule, fallbackExitRule(nameText));
            const summaryText = [timeframeText ? `${timeframeText} 信号轮询` : '', modeText || '']
                .filter(Boolean)
                .join(' · ') || '--';

            if (status?.strategy_v2) {
                return {
                    source: 'v2',
                    summaryText,
                    riskGuardText,
                    entryRuleText: fallbackEntry,
                    exitRuleText: fallbackExit,
                    takeProfitText: compactTakeProfit(strategy.takeProfit),
                    stopLossText: compactStopLoss(strategy.stopLoss),
                    leverageText: compactLeverage(strategy.leverage),
                    positionSizeText: compactText(strategy.positionSize, '--'),
                    coins: Array.isArray(strategy.coins) ? strategy.coins : [],
                };
            }

            return {
                source: 'locked-v2',
                summaryText,
                riskGuardText,
                entryRuleText: fallbackEntryRule(nameText),
                exitRuleText: fallbackExitRule(nameText),
                takeProfitText: '--',
                stopLossText: '--',
                leverageText: '--',
                positionSizeText: '--',
                coins: Array.isArray(status?.watchlist) ? status.watchlist : [],
            };
        }

        function updateStrategy(status) {
            const displayStrategy = resolveDisplayStrategy(status);
            document.getElementById('strategySummary').textContent = displayStrategy.summaryText;
            document.getElementById('strategyHeroLeverage').textContent = displayStrategy.leverageText || '--';
            document.getElementById('strategyCoins').textContent = (displayStrategy.coins && displayStrategy.coins.length > 0) ? displayStrategy.coins.join(', ') : '--';
        }

        function updateStatus(status) {
        }

        function applyLiveChipState(data = {}) {
            // Disabled legacy Freqtrade status overriding 
        }

        function syncTradingRuntimeState(isRunning) {
            if (!isRunning) {
                tradingActive = false;
                tradingElapsedWhenStopped = 0;
                if (tradingTimerInterval) {
                    clearInterval(tradingTimerInterval);
                    tradingTimerInterval = null;
                }
                return;
            }

            tradingActive = true;
            tradingStartTime = resolveTradingStartTime();
            if (!tradingTimerInterval) {
                tradingTimerInterval = setInterval(updateElapsedDisplay, 1000);
            }
        }

        function resetDashboardView(sessionInfo = null) {
            tradeSignature = '';
            thoughtSignature = '';
            latestTrades = [];
            latestThoughts = [];
            latestOpenPosition = null;
            latestMarketState = null;

            if (sessionInfo) {
                latestSession = sessionInfo;
                tradingStartTime = parseSessionStart(sessionInfo.started_at) || Date.now();
            } else {
                tradingStartTime = Date.now();
            }

            updateMetric('positionPnl', '0.00 USDT', 'neutral');
            updateMetric('totalPnl', '0.00 USDT', 'neutral');
            updateMetric('totalTrades', '00', 'neutral');
            updateMetric('winRate', '--', 'neutral');

            document.getElementById('positionTable').innerHTML =
                '<tr><td colspan="7" class="table-empty">新会话已开始，等待持仓</td></tr>';
            document.getElementById('tradeTable').innerHTML =
                '<tr><td colspan="7" class="table-empty">新会话已开始，等待交易记录</td></tr>';
            document.getElementById('thinkingList').innerHTML =
                '<div class="empty-state">新会话已开始，等待 AI 思考中...</div>';
        }

        async function updateFreqtradeStatus() {
            try {
                const data = await fetchJson(`${LOCAL_API_BASE}/api/freqtrade/status`);

                if (data?.session) {
                    latestSession = data.session;
                }
                applyLiveChipState(data);
                syncTradingRuntimeState(Boolean(data?.running));

                if (Array.isArray(data?.positions) && data.positions.length > 0) {
                    updateFreqtradePositions(data.positions);
                }
            } catch (e) {
                console.log('Freqtrade未连接:', e);
                applyLiveChipState({ running: false, error: 'Freqtrade 未连接' });
                syncTradingRuntimeState(false);
            }
        }
        
        function updateFreqtradePositions(trades) {
            console.log('Freqtrade持仓:', trades);
        }
        // Interval removed

        let tradingActive = false;
        let tradingStartTime = null;
        let tradingElapsedWhenStopped = 0;
        let tradingTimerInterval = null;
        let latestThoughts = [];

        function formatElapsed(ms) {
            const totalSec = Math.floor(ms / 1000);
            const h = String(Math.floor(totalSec / 3600)).padStart(2, '0');
            const m = String(Math.floor((totalSec % 3600) / 60)).padStart(2, '0');
            const s = String(totalSec % 60).padStart(2, '0');
            return `${h}:${m}:${s}`;
        }

        function parseSessionStart(value) {
            if (!value) return null;
            const date = parseSourceTimestamp(value);
            return date && Number.isFinite(date.getTime()) ? date.getTime() : null;
        }

        function resolveTradingStartTime(sessionInfo = latestSession, status = latestStatus) {
            return (
                parseSessionStart(sessionInfo?.started_at)
                || parseSessionStart(status?.session_started_at)
                || tradingStartTime
            );
        }

        function updateElapsedDisplay() {
            if (!tradingActive) return;
        }

        async function checkInitialBotStatus() {
            try {
                const [data, sessionInfo] = await Promise.all([
                    fetchJson(`${LOCAL_API_BASE}/api/bot/status`),
                    fetchJson(`${LOCAL_API_BASE}/api/session`).catch(() => null)
                ]);
                applyLiveChipState(data);
                latestSession = sessionInfo && sessionInfo.status !== 'no_session' ? sessionInfo : null;
                if (data.status === 'running') {
                    syncTradingRuntimeState(true);
                    if (typeof loadData === 'function') loadData();
                } else {
                    syncTradingRuntimeState(false);
                }
            } catch (e) {
                console.log('Local backend not reachable on init.');
            }
        }
        
        // Timeout removed

        async function toggleTrading() {
            if (!tradingActive) {
                try {
                    const data = await fetchJson(`${LOCAL_API_BASE}/api/bot/start`, { method: 'POST' });
                    const startOk = data.status === 'started' || data.status === 'already_running';
                    if (!startOk) {
                        console.error('Unexpected start response:', data);
                        applyLiveChipState({ running: false, error: 'Freq 启动失败' });
                        syncTradingRuntimeState(false);
                        return;
                    }

                    resetDashboardView(data.session || null);
                    await updateFreqtradeStatus();
                    await loadData();
                } catch (e) {
                    console.warn('Local bot server not reachable. Ensure server.py is running on port 5000.', e);
                    applyLiveChipState({ running: false, error: 'Freq 启动失败' });
                    syncTradingRuntimeState(false);
                }
            } else {
                try {
                    const data = await fetchJson(`${LOCAL_API_BASE}/api/bot/stop`, { method: 'POST' });
                    const stopOk = data.status === 'stopped' || data.status === 'already_stopped';
                    if (!stopOk) {
                        console.error('Unexpected stop response:', data);
                        applyLiveChipState({ running: true, error: 'Freq 停止失败' });
                        return;
                    }

                    resetDashboardView(data.session || null);
                    await updateFreqtradeStatus();
                    await loadData();
                } catch (e) {
                    console.warn('Local bot server not reachable.', e);
                    applyLiveChipState({ running: true, error: 'Freq 停止失败' });
                }
            }
        }

        let streamingActive = false;

        function toggleStreaming() {
            const chip = document.getElementById('streamingChip');
            const label = document.getElementById('streamingLabel');

            if (!streamingActive) {
                streamingActive = true;
                label.textContent = '直播中';
                chip.classList.add('is-active');
            } else {
                streamingActive = false;
                label.textContent = '直播关';
                chip.classList.remove('is-active');
            }
        }

        const BROADCAST_IDLE = [
            '🎙️ 欢迎来到小OC的直播间！点个关注不迷路~',
            '🎉 新进来的观众朋友们，小OC给你们比心 ❤️',
            '👋 各位大佬好！AI交易员小OC在线营业中~',
            '🔥 直播间人气越来越旺了！感谢各位的陪伴',
            '💬 有问题弹幕扣1，小OC看到会回复哦',
            '🌟 感谢 *** 进入直播间！欢迎欢迎~',
            '🎊 直播间的兄弟们，今天咱们一起见证奇迹！',
            '📢 关注小OC，每天直播AI自动交易实况！',
            '🤖 别人的AI写诗画画，我的AI在币圈搬砖',
            '💰 我不是在赚钱，就是在亏钱的路上',
            '📊 AI说：我分析了一万根K线，结论是再看看',
            '🧠 小OC的脑子比你的基金经理靠谱（大概）',
            '😂 你这AI靠谱吗？小OC：你猜？',
            '🎰 有人炒币靠运气，小OC靠的是也有点运气',
            '🐶 狗庄别跑！小OC的AI盯上你了',
            '☕ 让AI干活，我喝咖啡，科技的力量',
            '💸 赚了是AI厉害，亏了是市场的错',
            '🎪 今日节目：看AI如何在币圈翻云覆雨',
            '🐸 心态好扣666，心态崩了扣SOS',
            '🦊 该出手时就出手，不该出手时看戏',
            '📈 交易第一铁律：永远不要All In',
            '🛡️ 止损是安全气囊，永远不要拆掉它',
            '⏰ 耐心等待是交易中最值钱的技能',
            '🎯 好的交易不是赚得多，而是亏得少',
            '💡 趋势是你的朋友，直到它转弯那一秒',
            '📉 会买的是徒弟，会卖的才是师傅',
            '🧘 控制情绪 = 控制风险 = 控制利润',
            '🔑 资金管理决定你能在市场活多久',
            '🎓 不懂的币不碰，看不懂的行情不做',
        ];

        const BROADCAST_TRADING = [
            '⚡ AI正在全力扫描，猎物随时出现！',
            '🔥 交易引擎已启动，让子弹飞一会儿~',
            '🎯 AI瞄准了目标，等待最佳入场时机...',
            '🚀 引擎轰鸣中！坐稳了各位！',
            '🧪 小OC正在分析K线密码...',
            '🕵️ AI探员正在秘密调查主力动向...',
            '🎲 策略就位，子弹已上膛，等风来！',
            '🦈 鲨鱼已入水，正在寻找猎物...',
            '⚙️ 量化引擎高速运转中！别眨眼！',
            '🏴‍☠️ 海盗船已出发，目标：利润！',
            '🔮 AI水晶球显示：有机会正在靠近...',
            '🎪 好戏即将开场！各位准备好爆米花~',
        ];

        function buildBroadcastHtml(messages) {
            const items = messages.map(msg => `<div class="broadcast-item">${msg}</div>`);
            const withSeps = [];
            items.forEach((item, i) => {
                if (i > 0) withSeps.push('<span class="broadcast-sep">✦</span>');
                withSeps.push(item);
            });
            const segment = `<div class="broadcast-segment">${withSeps.join('')}</div>`;
            return segment + segment;
        }

        let lastBroadcastIndex = 0;
        let pendingBroadcastData = null;
        let broadcastInitialized = false;

        function applyBroadcast(data) {
            const { marketSymbol, marketPrice, totalPnl, trades } = data;
            const pool = tradingActive ? [...BROADCAST_IDLE, ...BROADCAST_TRADING] : BROADCAST_IDLE;
            const shuffled = [...pool].sort(() => Math.random() - 0.5);
            const selected = shuffled.slice(0, 6);

            const dataItems = [];
            if (marketPrice) dataItems.push(`📊 <strong>${marketSymbol}</strong> 实时 <strong>${marketPrice.toFixed(2)} USDT</strong>`);
            if (totalPnl !== 0) dataItems.push(`💰 本轮收益 <strong>${formatSigned(totalPnl)} USDT</strong>`);
            if (trades && trades.length > 0) dataItems.push(`⚡ 已成交 <strong>${trades.length}</strong> 笔`);
            if (dataItems.length) selected.splice(3, 0, dataItems[Math.floor(Math.random() * dataItems.length)]);

            const track = document.getElementById('broadcastTrack');
            track.innerHTML = buildBroadcastHtml(selected);

            const segWidth = track.querySelector('.broadcast-segment')?.offsetWidth || 2000;
            const speed = 60;
            const duration = segWidth / speed;
            track.style.setProperty('--ticker-duration', `${duration}s`);
        }

        function updateBroadcastFeed(data) {
            pendingBroadcastData = data;

            if (!broadcastInitialized) {
                broadcastInitialized = true;
                applyBroadcast(data);

                const track = document.getElementById('broadcastTrack');
                track.addEventListener('animationiteration', () => {
                    if (pendingBroadcastData) {
                        applyBroadcast(pendingBroadcastData);
                        pendingBroadcastData = null;
                    }
                });
            }
        }

        function updateThinking(thoughts) {
            const list = document.getElementById('thinkingList');
            if (!thoughts || thoughts.length === 0) {
                list.innerHTML = '<div class="empty-state">暂无思考数据</div>';
                return;
            }

            latestThoughts = thoughts;
            const sessionThoughts = thoughts;

            if (!sessionThoughts.length) {
                list.innerHTML = '<div class="empty-state">新会话已开始，等待 MiniMax AI 思考中...</div>';
                return;
            }

            const signature = `${sessionThoughts.length}-${sessionThoughts[sessionThoughts.length - 1]?.time || ''}`;
            if (signature === thoughtSignature) return;
            thoughtSignature = signature;

            const actionColors = {
                'OPEN_LONG': '#00f7b2', 'OPEN_SHORT': '#ff5f7c',
                'CLOSE_LONG': '#ffd36c', 'CLOSE_SHORT': '#ffd36c',
                'HOLD': '#6cb7ff', 'ERROR': '#ff5f7c'
            };
            const actionLabels = {
                'OPEN_LONG': '做多', 'OPEN_SHORT': '做空',
                'CLOSE_LONG': '平多', 'CLOSE_SHORT': '平空',
                'HOLD': '观望', 'ERROR': '异常'
            };

            const items = sessionThoughts.slice().reverse().slice(0, window.innerWidth <= 720 ? 18 : 20);
            list.innerHTML = items.map((item, index) => {
                const action = item.action || '';
                const color = actionColors[action] || '#6cb7ff';
                const label = actionLabels[action] || '';
                const confidence = item.confidence != null ? (Number(item.confidence) * 100).toFixed(0) : '';
                const instrument = item.instrument || '';
                const model = item.model || '';

                let badge = '';
                if (label) {
                    badge = `<span style="display:inline-block; padding:1px 6px; border-radius:4px; font-size:0.7rem; font-weight:600; background:${color}22; color:${color}; border:1px solid ${color}44; margin-right:6px;">${label}</span>`;
                }
                if (instrument) {
                    badge += `<span style="font-size:0.72rem; color:var(--text-soft); margin-right:6px;">${instrument}</span>`;
                }
                if (confidence) {
                    badge += `<span style="font-size:0.68rem; color:var(--text-mute);">信心 ${confidence}%</span>`;
                }

                return `
                    <div class="thinking-item ${index === 0 ? 'new' : ''}">
                        <div class="thinking-time">${formatBeijingCompact(item.time)}${model ? ` <span style="font-size:0.6rem;color:var(--text-mute);">${model}</span>` : ''}</div>
                        ${badge ? `<div style="margin-bottom:3px;">${badge}</div>` : ''}
                        <div class="thinking-body">${item.thought || ''}</div>
                    </div>
                `;
            }).join('');
        }

        function updateTradePanelMode() {
            const panel = document.getElementById('tradePanel');
            const title = document.getElementById('tradePanelTitle');
            const desc = document.getElementById('tradePanelDesc');
            const chipLabel = document.getElementById('tradePanelChipLabel');
            const label = document.getElementById('tradePanelModeLabel');
            const positionView = document.getElementById('positionView');
            const tradeTableView = document.getElementById('tradeTableView');
            const showPosition = tradePanelMode === 'position';

            label.textContent = showPosition ? '当前持仓' : '交易记录';
            title.textContent = showPosition ? '当前持仓' : '交易记录';
            desc.textContent = showPosition ? '实时持仓和浮盈浮亏。' : '成交和曲线直接对照。';
            chipLabel.textContent = showPosition ? '持仓视图' : '记录视图';
            panel.classList.toggle('mode-position', showPosition);
            panel.classList.toggle('mode-trades', !showPosition);
            positionView.classList.toggle('is-hidden', !showPosition);
            tradeTableView.classList.toggle('is-hidden', showPosition);
        }

        function toggleTradePanelMode() {
            tradePanelMode = tradePanelMode === 'position' ? 'trades' : 'position';
            updateTradePanelMode();
        }

        function updatePositions(status, marketState, trades) {
            const tbody = document.getElementById('positionTable');
            const positions = Array.isArray(status?.open_positions) ? status.open_positions : [];

            if (!positions.length) {
                tbody.innerHTML = '<tr><td colspan="7" class="table-empty">当前空仓</td></tr>';
                return;
            }

            tbody.innerHTML = positions.map((position) => {
                const direction = (position.direction || 'long') === 'short' ? 'short' : 'long';
                const entryPrice = Number(position.entryPrice) || 0;
                const currentPrice = Number(position.markPrice) || Number(marketState?.price) || entryPrice;
                const unrealized = Number(position.unrealizedProfit) || 0;
                const pnlClass = unrealized > 0 ? 'pnl-positive' : unrealized < 0 ? 'pnl-negative' : 'pnl-flat';
                const openedTrade = Array.isArray(trades)
                    ? [...trades].reverse().find((trade) => {
                        const tradeDirection = (trade.direction || 'long') === 'short' ? 'short' : 'long';
                        return trade.symbol === position.symbol
                            && tradeDirection === direction
                            && String(trade.tradeAction || '').toUpperCase() === 'OPEN';
                    })
                    : null;

                return `
                    <tr>
                        <td>${formatBeijingCompact(openedTrade?.time)}</td>
                        <td><span class="dir-badge ${direction}">${direction === 'long' ? '做多' : '做空'}</span></td>
                        <td>${(position.symbol || '--').replace('USDT', '')}</td>
                        <td>${entryPrice.toFixed(2)}</td>
                        <td>${currentPrice.toFixed(2)}</td>
                        <td>${position.leverage ? `${position.leverage}x` : '--'}</td>
                        <td class="${pnlClass}">${formatSigned(unrealized)} USDT</td>
                    </tr>
                `;
            }).join('');
        }

        function updateTrades(trades, openTrade, openPosition) {
            const tbody = document.getElementById('tradeTable');
            if (!trades || trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="table-empty">暂无交易记录</td></tr>';
                return;
            }

            const signature = `${trades.length}-${trades[trades.length - 1]?.time || ''}`;
            if (signature === tradeSignature) return;
            tradeSignature = signature;

            tbody.innerHTML = trades.slice().reverse().map((trade) => {
                const isBuy = trade.type === 'BUY';
                const direction = (trade.direction || 'long') === 'short' ? 'short' : 'long';
                const isCurrentOpenTrade = openTrade === trade && openPosition;
                const pnl = isCurrentOpenTrade ? Number(openPosition.unrealizedProfit) : Number(trade.pnl);
                const pnlClass = Number.isFinite(pnl) ? (pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : 'pnl-flat') : 'pnl-flat';
                const pnlText = Number.isFinite(pnl) ? formatSigned(pnl) : '--';
                const tradeText = isBuy ? '买入' : '卖出';
                const directionText = direction === 'long' ? '做多' : '做空';

                return `
                    <tr>
                        <td>${formatBeijingCompact(trade.time)}</td>
                        <td class="${isBuy ? 'action-buy' : 'action-sell'}">${tradeText}</td>
                        <td><span class="dir-badge ${direction}">${directionText}</span></td>
                        <td>${(trade.symbol || '--').replace('USDT', '')}</td>
                        <td>${Number(trade.price).toFixed(2)}</td>
                        <td>${trade.leverage ? `${trade.leverage}x` : '--'}</td>
                        <td class="${pnlClass}">${pnlText}</td>
                    </tr>
                `;
            }).join('');
        }

        function buildChartSeries(trades, status) {
            const startTime = latestSession?.started_at || latestStatus?.session_started_at || tradingStartTime;
            const startBalance = Number(status?.start_balance) || Number(latestStatus?.start_balance) || initialBalance;
            const equityHistory = Array.isArray(status?.equity_history) ? status.equity_history : [];
            const currentEquity = Number(status?.equity) || Number(status?.balance) || startBalance;
            if (!trades || !trades.length) {
                if (equityHistory.length) {
                    return {
                        startLabel: formatChartTime(startTime ? new Date(String(startTime).replace(' ', 'T')) : new Date()),
                        startBalance,
                        history: equityHistory.map((point) => ({
                            time: point.time,
                            balance: Number(point.equity) || Number(point.balance) || startBalance
                        }))
                    };
                }
                return {
                    startLabel: formatChartTime(startTime ? new Date(String(startTime).replace(' ', 'T')) : new Date()),
                    startBalance,
                    history: currentEquity !== startBalance ? [{
                        time: status?.last_run || startTime,
                        balance: currentEquity
                    }] : []
                };
            }

            const history = equityHistory.length
                ? equityHistory.map((point) => ({
                    time: point.time,
                    balance: Number(point.equity) || Number(point.balance) || startBalance
                }))
                : trades.map((t) => ({
                    time: t.time,
                    balance: Number(t.balance) || startBalance
                }));

            return {
                startLabel: formatChartTime(startTime ? new Date(String(startTime).replace(' ', 'T')) : new Date()),
                startBalance,
                history,
            };
        }

        function shouldShowTick(index, total) {
            if (total <= 1) return true;
            const targetCount = window.innerWidth <= 720 ? 4 : 6;
            if (index === 0 || index === total - 1) return true;
            const step = Math.max(1, Math.ceil((total - 1) / Math.max(targetCount - 1, 1)));
            return index % step === 0;
        }

        function updateChart(trades, status) {
            const ctx = document.getElementById('balanceChart').getContext('2d');
            const series = buildChartSeries(trades, status || latestStatus);
            const labels = [series.startLabel, ...series.history.map((point) => formatChartTime(point.time))];
            const balances = [series.startBalance, ...series.history.map((point) => point.balance)];
            
            const minBalance = Math.min(...balances);
            const maxBalance = Math.max(...balances);
            const dynamicRange = maxBalance - minBalance;
            const padding = Math.max(dynamicRange * 0.22, 0.3);
            const pointRadius = window.innerWidth <= 720 ? 2.2 : 1.6;
            const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height || 260);
            gradient.addColorStop(0, 'rgba(0, 247, 178, 0.38)');
            gradient.addColorStop(1, 'rgba(0, 247, 178, 0.02)');

            if (chart) {
                chart.data.labels = labels;
                chart.data.datasets[0].data = balances;
                chart.data.datasets[0].backgroundColor = gradient;
                chart.data.datasets[0].pointRadius = pointRadius;
                chart.options.scales.x.ticks.callback = (value, index) => (
                    shouldShowTick(index, labels.length) ? labels[index] : ''
                );
                chart.options.scales.y.suggestedMin = minBalance - padding;
                chart.options.scales.y.suggestedMax = maxBalance + padding;
                chart.resize();
                chart.update('none');
                return;
            }

            chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels,
                    datasets: [{
                        data: balances,
                        borderColor: '#00f7b2',
                        backgroundColor: gradient,
                        borderWidth: 3.4,
                        fill: true,
                        tension: 0.28,
                        pointRadius,
                        pointHoverRadius: 5.4,
                        pointBackgroundColor: '#d8fff5',
                        pointBorderColor: '#00f7b2',
                        pointBorderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: {
                            bottom: 20
                        }
                    },
                    animation: {
                        duration: 360
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            backgroundColor: 'rgba(5, 12, 23, 0.95)',
                            borderColor: 'rgba(0, 247, 178, 0.2)',
                            borderWidth: 1,
                            titleColor: '#f4fbff',
                            bodyColor: '#d8e7ff',
                            displayColors: false
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                display: false
                            },
                            ticks: {
                                color: 'rgba(224, 236, 255, 0.68)',
                                autoSkip: false,
                                maxRotation: 0,
                                minRotation: 0,
                                padding: 10,
                                callback(value, index) {
                                    return shouldShowTick(index, labels.length) ? labels[index] : '';
                                }
                            },
                            border: {
                                color: 'rgba(118, 167, 255, 0.18)'
                            }
                        },
                        y: {
                            grid: {
                                color: 'rgba(118, 167, 255, 0.08)'
                            },
                            ticks: {
                                color: 'rgba(224, 236, 255, 0.58)',
                                maxTicksLimit: window.innerWidth <= 720 ? 5 : 6,
                                padding: 8
                            },
                            suggestedMin: minBalance - padding,
                            suggestedMax: maxBalance + padding
                        }
                    }
                }
                });
        }

        function refreshStaticPanels() {
            updateTradePanelMode();
            if (latestStatus) {
                updatePositions(latestStatus, latestMarketState, latestTrades);
            }
            updateChart(latestTrades, latestStatus);
        }

        const MARKET_COINS = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 'DOGE-USDT-SWAP'];
        const COIN_LABELS = { 'BTC-USDT-SWAP': 'BTC', 'ETH-USDT-SWAP': 'ETH', 'SOL-USDT-SWAP': 'SOL', 'DOGE-USDT-SWAP': 'DOGE' };

        async function fetchMarketOverview() {
            try {
                const [tickerRes, fundingRes] = await Promise.allSettled([
                    fetch('https://www.okx.com/api/v5/market/tickers?instType=SWAP').then(r => r.json()),
                    Promise.all(MARKET_COINS.map(s =>
                        fetch(`https://www.okx.com/api/v5/public/funding-rate?instId=${s}`).then(r => r.json())
                    )),
                ]);

                const allTickers = tickerRes.status === 'fulfilled' ? (tickerRes.value?.data || []) : [];
                const fundings = fundingRes.status === 'fulfilled' ? fundingRes.value : [];

                MARKET_COINS.forEach((instId, idx) => {
                    const label = COIN_LABELS[instId];
                    const ticker = allTickers.find(t => t.instId === instId);
                    const fundingData = fundings[idx]?.data?.[0];

                    const priceEl = document.getElementById(`price-${label}`);
                    if (priceEl && ticker) {
                        const price = parseFloat(ticker.last);
                        priceEl.textContent = price >= 1000 ? price.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 }) : price.toFixed(4);
                    }

                    const changeEl = document.getElementById(`change-${label}`);
                    if (changeEl && ticker) {
                        const open24h = parseFloat(ticker.open24h);
                        const last = parseFloat(ticker.last);
                        const pct = open24h > 0 ? ((last - open24h) / open24h) * 100 : 0;
                        changeEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
                        changeEl.className = 'coin-change ' + (pct >= 0 ? 'up' : 'down');
                    }

                    const extraEl = document.getElementById(`extra-${label}`);
                    if (extraEl) {
                        const fr = fundingData?.fundingRate ? (parseFloat(fundingData.fundingRate) * 100).toFixed(4) + '%' : '--';
                        const vol = ticker?.vol24h ? parseFloat(ticker.vol24h).toLocaleString('en-US', {maximumFractionDigits: 0}) : '--';
                        extraEl.textContent = `资费 ${fr} | 24h量 ${vol}`;
                    }
                });
            } catch (e) {
                console.warn('Market overview fetch error:', e);
            }
        }

        fetchMarketOverview();
        setInterval(fetchMarketOverview, 10000);

        let activeTraderId = "";
        let cachedSystemConfig = null;
        let isEditingTrader = false;
        let scanIntervalId;
        let scanFrequency = 15000;
        
        setInterval(() => {
            document.getElementById('liveClock').textContent = new Date().toLocaleTimeString('zh-CN', {hour12:false});
        }, 1000);

        function changeActiveTrader() {
            activeTraderId = document.getElementById('activeTraderSelect').value;
            loadData();
        }

        async function loadData() {
            if(!activeTraderId) {
                document.getElementById('liveLabel').textContent = '未选择实例';
                document.getElementById('statusDot').className = 'status-dot';
                document.getElementById('liveChip').classList.remove('is-active');
                return;
            }
            try {
                const bust = `t=${Date.now()}`;
                let thoughts, trades, status;
                try {
                    [thoughts, trades, status] = await Promise.all([
                        fetchJson(`${LOCAL_API_BASE}/data/${activeTraderId}/thinking.json?${bust}`),
                        fetchJson(`${LOCAL_API_BASE}/data/${activeTraderId}/trades.json?${bust}`),
                        fetchJson(`${LOCAL_API_BASE}/data/${activeTraderId}/status.json?${bust}`)
                    ]);
                } catch(e) { }

                const displayStrategy = resolveDisplayStrategy(status);
                const openPosition = findOpenPosition(trades, status);
                const openTrade = findOpenTrade(trades);
                const marketSymbol = openPosition?.symbol || 'BTC-USDT-SWAP';
                const marketState = openPosition?.markPrice
                    ? { price: Number(openPosition.markPrice) || 0, pnl: Number(openPosition.unrealizedProfit) || 0 }
                    : await getMarketState(marketSymbol, openPosition?.entryPrice ?? openPosition?.price, openPosition?.direction, openPosition?.amount);

                latestTrades = trades || [];
                latestStatus = status || {};
                latestOpenPosition = openPosition;
                latestMarketState = marketState;

                refreshStaticPanels();
                updateThinking(thoughts);
                updateTrades(latestTrades, openTrade, openPosition);
                updateStrategy(latestStatus);
                updateStatus(latestStatus);

                const currentBalance = (latestStatus?.equity != null) ? Number(latestStatus.equity) : ((latestStatus?.balance != null) ? Number(latestStatus.balance) : initialBalance);
                const baseCapital = (latestStatus?.start_balance != null) ? Number(latestStatus.start_balance) : initialBalance;
                const totalPnl = (currentBalance - baseCapital);
                const tradesSinceStart = latestTrades.length;
                const closedTrades = latestTrades.filter((t) => String(t.tradeAction).toUpperCase() === 'CLOSE');
                const winningTrades = closedTrades.filter((t) => Number(t.pnl) > 0).length;
                const winRate = closedTrades.length ? (winningTrades / closedTrades.length) * 100 : null;
                const displayPositionPnl = Number(latestStatus?.unrealized_pnl) || 0;

                updateMetric('currentBalance', `${currentBalance.toFixed(2)} USDT`, totalPnl > 0 ? 'positive' : (totalPnl < 0 ? 'negative' : 'neutral'));
                updateMetric('positionPnl', `${formatSigned(displayPositionPnl)} USDT`, displayPositionPnl > 0 ? 'positive' : (displayPositionPnl < 0 ? 'negative' : 'neutral'));
                updateMetric('totalPnl', `${formatSigned(totalPnl)} USDT`, totalPnl > 0 ? 'positive' : (totalPnl < 0 ? 'negative' : 'neutral'));
                updateMetric('totalTrades', String(tradesSinceStart).padStart(2, '0'), 'neutral');
                updateMetric('winRate', winRate === null ? '--' : `${winRate.toFixed(1)}%`, winRate === null ? 'neutral' : (winRate >= 55 ? 'positive' : (winRate >= 45 ? 'neutral' : 'negative')));

                let yieldRate = (baseCapital > 0 ? ((currentBalance - baseCapital) / baseCapital * 100) : 0);
                updateMetric('yieldRate', `${yieldRate >= 0 ? '+' : ''}${yieldRate.toFixed(2)}%`, yieldRate > 0 ? 'positive' : (yieldRate < 0 ? 'negative' : 'neutral'));

                updateBroadcastFeed({
                    marketSymbol, marketPrice: marketState.price, positionPnl: displayPositionPnl,
                    totalPnl, trades: latestTrades, strategy: displayStrategy, status: latestStatus
                });
                
                const isRunning = cachedSystemConfig?.traders?.[activeTraderId]?.status === 'running';
                const freq = cachedSystemConfig?.traders?.[activeTraderId]?.scan_frequency || '30';
                const aiScanFreqEl = document.getElementById('aiScanFreq');
                if(aiScanFreqEl) aiScanFreqEl.textContent = freq + '秒';
                const traderName = cachedSystemConfig?.traders?.[activeTraderId]?.name || '';
                document.getElementById('liveLabel').textContent = isRunning ? `${traderName || '交易引擎'}` : `${traderName || '交易机'} (已停止)`;
                document.getElementById('liveChip').className = isRunning ? 'live-chip is-active' : 'live-chip';
            } catch (error) {
                console.error('loadData failed:', error);
            }
        }

        async function fetchSystemSettings() {
            try {
                const res = await fetch('/api/system/config');
                if(res.ok) {
                    const settings = await res.json();
                    cachedSystemConfig = settings;
                    const brand = settings.web_brand || 'OpenClaw';
                    const title = settings.web_title || 'OKX AI Trading Challenge';
                    document.title = `${brand} - ${title}`;
                    const brandEl = document.getElementById('brandName');
                    const subtitleEl = document.getElementById('brandSubtitle');
                    if (brandEl) brandEl.textContent = brand;
                    if (subtitleEl) subtitleEl.textContent = title;
                    document.forms['settingsForm'].web_brand.value = brand;
                    document.forms['settingsForm'].web_title.value = title;

                    const aiProviders = settings.ai_providers || {};
                    
                    const aiSelect = document.getElementById('form_ai_provider');
                    if (aiSelect) {
                        aiSelect.innerHTML = '';
                        for (let k in aiProviders) {
                            const opt = document.createElement('option');
                            opt.value = k; opt.textContent = k;
                            aiSelect.appendChild(opt);
                        }
                    }
                    
                    const firstAiKey = Object.keys(aiProviders)[0];
                    if (firstAiKey) {
                        const ai = aiProviders[firstAiKey];
                        document.getElementById('ai_node_id').value = firstAiKey;
                        document.getElementById('ai_api_key').value = ai.api_key || '';
                        document.getElementById('ai_base_url').value = ai.base_url || 'https://api.minimax.io/v1';
                        const modelSelect = document.getElementById('ai_model');
                        if (ai.model) {
                            for (let opt of modelSelect.options) {
                                if (opt.value === ai.model) { opt.selected = true; break; }
                            }
                        }
                    }
                    const exchanges = settings.exchanges || {};

                    const exSelect = document.getElementById('form_exchange');
                    if (exSelect) {
                        exSelect.innerHTML = '';
                        for (let k in exchanges) {
                            const opt = document.createElement('option');
                            opt.value = k; opt.textContent = k;
                            exSelect.appendChild(opt);
                        }
                    }
                    const firstExKey = Object.keys(exchanges)[0];
                    if (firstExKey) {
                        const ex = exchanges[firstExKey];
                        document.getElementById('ex_node_id').value = firstExKey;
                        document.getElementById('ex_api_key').value = ex.api_key || '';
                        document.getElementById('ex_secret_key').value = ex.secret_key || '';
                        document.getElementById('ex_passphrase').value = ex.passphrase || '';
                        document.getElementById('ex_is_demo').checked = !!ex.is_demo;
                        if(document.getElementById('ex_competition_mode')) {
                            document.getElementById('ex_competition_mode').checked = !!ex.competition_mode;
                        }
                    }
                }
            } catch(e){}
        }

        async function fetchTradersList() {
            if (isEditingTrader) return;
            try {
                const res = await fetch('/api/traders');
                if(res.ok) {
                    const data = await res.json();
                    const traders = data.traders || {};
                    const select = document.getElementById('activeTraderSelect');
                    const cVal = select.value;
                    select.innerHTML = '';
                    
                    const listContainer = document.getElementById('traderListContainer');
                    listContainer.innerHTML = '';
                    
                    if(Object.keys(traders).length === 0) {
                        select.innerHTML = '<option value="">暂无交易员</option>';
                        listContainer.innerHTML = '<div class="empty-state">目前还没有激活任何交易员。</div>';
                        return;
                    }

                    for(const [tid, info] of Object.entries(traders)) {
                        const opt = document.createElement('option');
                        opt.value = tid;
                        opt.textContent = `${info.name} [${info.status.toUpperCase()}]`;
                        opt.style.background = "#0a1324";
                        select.appendChild(opt);
                        
                        const statusColor = info.status === 'running' ? '#00f7b2' : '#ff5f7c';
                        const isRunning = info.status === 'running';
                        const freq = info.scan_frequency || 30;
                        
                        listContainer.innerHTML += `
                        <div id="trader-card-${tid}" style="border: 1px solid rgba(118,167,255,0.2); border-radius: var(--radius-sm); padding: 14px; margin-bottom: 8px;">
                            <div id="trader-view-${tid}" style="display:flex; justify-content:space-between; align-items:center;">
                                <div style="flex:1;">
                                    <h4 style="color:var(--text); margin-bottom:4px;">${info.name} <span style="font-size:0.7rem; color:${statusColor}; border:1px solid ${statusColor}; padding:2px 4px; border-radius:4px; margin-left:6px;">${info.status}</span></h4>
                                    <div style="font-size:0.78rem; color:var(--text-mute); display:flex; gap:12px; flex-wrap:wrap;">
                                        <span>🤖 ${info.ai_provider || '--'}</span>
                                        <span>📈 ${info.exchange || '--'}</span>
                                        <span>⏱️ ${freq}s</span>
                                    </div>
                                </div>
                                <div style="display:flex; gap:6px; flex-shrink:0;">
                                    ${!isRunning ? `<button class="btn" style="background:rgba(108,183,255,0.15); color:var(--blue); border:1px solid rgba(108,183,255,0.3); padding:6px 10px; font-size:0.78rem;" onclick="editTrader('${tid}')" title="编辑">✏️</button>` : ''}
                                    ${!isRunning
                                        ? `<button class="btn" style="background:#00f7b2; color:#000; padding:6px 12px; font-size:0.8rem;" onclick="startTrader('${tid}')">▶ 启动</button>`
                                        : `<button class="btn" style="background:#ff5f7c; color:#fff; padding:6px 12px; font-size:0.8rem;" onclick="stopTrader('${tid}')">■ 停止</button>`
                                    }
                                    ${!isRunning ? `<button class="btn btn-cancel" style="padding:6px 12px; font-size:0.8rem;" onclick="deleteTrader('${tid}')">删除</button>` : ''}
                                </div>
                            </div>
                            <div id="trader-edit-${tid}" style="display:none; margin-top:12px; border-top:1px solid rgba(118,167,255,0.15); padding-top:12px;">
                                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                                    <div class="form-group"><label class="form-label">名称</label><input class="form-input" id="edit-name-${tid}" value="${info.name}"></div>
                                    <div class="form-group"><label class="form-label">扫描频率(秒)</label><input class="form-input" id="edit-freq-${tid}" type="number" value="${freq}"></div>
                                    <div class="form-group"><label class="form-label">绑定 AI</label><select class="form-input form-select" id="edit-ai-${tid}"></select></div>
                                    <div class="form-group"><label class="form-label">绑定交易所</label><select class="form-input form-select" id="edit-ex-${tid}"></select></div>
                                </div>
                                <div style="display:flex; gap:8px; margin-top:10px; justify-content:flex-end;">
                                    <button class="btn btn-cancel" style="padding:6px 16px; font-size:0.8rem;" onclick="cancelEditTrader('${tid}')">取消</button>
                                    <button class="btn" style="background:#00f7b2; color:#000; padding:6px 16px; font-size:0.8rem;" onclick="saveEditTrader('${tid}')">💾 保存</button>
                                </div>
                            </div>
                        </div>`;
                    }
                    if(traders[cVal]) select.value = cVal;
                    else {
                        select.value = Object.keys(traders)[0];
                        activeTraderId = select.value;
                    }
                }
            } catch(e){}
        }

        window.startTrader = async function(tid) { await fetch(`/api/traders/${tid}/start`, {method:'POST'}); fetchTradersList(); }
        window.stopTrader = async function(tid) { await fetch(`/api/traders/${tid}/stop`, {method:'POST'}); fetchTradersList(); }
        window.deleteTrader = async function(tid) { if(!confirm('确定删除该交易员？')) return; await fetch(`/api/traders/${tid}`, {method:'DELETE'}); fetchTradersList(); }

        window.editTrader = function(tid) {
            isEditingTrader = true;
            document.getElementById(`trader-view-${tid}`).style.display = 'none';
            document.getElementById(`trader-edit-${tid}`).style.display = 'block';
            const aiSel = document.getElementById(`edit-ai-${tid}`);
            const exSel = document.getElementById(`edit-ex-${tid}`);
            aiSel.innerHTML = '';
            exSel.innerHTML = '';
            if(cachedSystemConfig) {
                const aiProviders = cachedSystemConfig.ai_providers || {};
                for(const [k] of Object.entries(aiProviders)) {
                    const o = document.createElement('option'); o.value = k; o.textContent = k; aiSel.appendChild(o);
                }
                const exchanges = cachedSystemConfig.exchanges || {};
                for(const [k] of Object.entries(exchanges)) {
                    const o = document.createElement('option'); o.value = k; o.textContent = k; exSel.appendChild(o);
                }
            }
            const traders = cachedSystemConfig?.traders || {};
            if(traders[tid]) {
                aiSel.value = traders[tid].ai_provider || '';
                exSel.value = traders[tid].exchange || '';
            }
        }

        window.cancelEditTrader = function(tid) {
            document.getElementById(`trader-view-${tid}`).style.display = 'flex';
            document.getElementById(`trader-edit-${tid}`).style.display = 'none';
            isEditingTrader = false;
        }

        window.saveEditTrader = async function(tid) {
            const name = document.getElementById(`edit-name-${tid}`).value.trim();
            const freq = document.getElementById(`edit-freq-${tid}`).value.trim();
            const ai = document.getElementById(`edit-ai-${tid}`).value;
            const ex = document.getElementById(`edit-ex-${tid}`).value;
            await fetch('/api/traders', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ id: tid, name, scan_frequency: freq, ai_provider: ai, exchange: ex })
            });
            isEditingTrader = false;
            await fetchTradersList();
            await fetchSystemSettings();
        }

        function switchTab_old(tab) {
            document.getElementById('tabSysBtn').className = tab === 'sys' ? 'btn' : 'btn btn-cancel';
            document.getElementById('tabSysBtn').style.background = tab === 'sys' ? '#00f7b2' : '';
            document.getElementById('tabSysBtn').style.color = tab === 'sys' ? '#000' : '';
            
            document.getElementById('tabBotsBtn').className = tab === 'bots' ? 'btn' : 'btn btn-cancel';
            document.getElementById('tabBotsBtn').style.background = tab === 'bots' ? '#00f7b2' : '';
            document.getElementById('tabBotsBtn').style.color = tab === 'bots' ? '#000' : '';
            
            document.getElementById('tab-sys').style.display = tab === 'sys' ? 'block' : 'none';
            document.getElementById('tab-bots').style.display = tab === 'bots' ? 'block' : 'none';
        }

        window.saveComponentConfig = async function(type) {
            let updates = {};
            if (type === 'ai') {
                const nodeId = document.getElementById('ai_node_id').value.trim() || 'minimax_1';
                updates.ai_providers = {
                    [nodeId]: {
                        type: 'minimax',
                        api_key: document.getElementById('ai_api_key').value.trim(),
                        base_url: document.getElementById('ai_base_url').value.trim() || 'https://api.minimax.io/v1',
                        model: document.getElementById('ai_model').value
                    }
                };
            }
            if (type === 'ex') {
                const nodeId = document.getElementById('ex_node_id').value.trim() || 'okx_1';
                updates.exchanges = {
                    [nodeId]: {
                        type: 'okx',
                        api_key: document.getElementById('ex_api_key').value.trim(),
                        secret_key: document.getElementById('ex_secret_key').value.trim(),
                        passphrase: document.getElementById('ex_passphrase').value.trim(),
                        is_demo: document.getElementById('ex_is_demo').checked
                    }
                };
            }
            try {
                const res = await fetch('/api/system/config', {
                    method:'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(updates)
                });
                if(res.ok) {
                    alert("保存成功！");
                    fetchSystemSettings();
                }
            } catch(e) { alert("网络错误"); }
        };

        window.testAiConnection = async function() {
            const resultEl = document.getElementById('aiTestResult');
            resultEl.style.display = 'block';
            resultEl.style.background = 'rgba(108,183,255,0.1)';
            resultEl.style.color = 'var(--cyan)';
            resultEl.textContent = '⏳ 正在通过服务器代理测试连接...';
            const apiKey = document.getElementById('ai_api_key').value.trim();
            const baseUrl = document.getElementById('ai_base_url').value.trim() || 'https://api.minimax.io/v1';
            const model = document.getElementById('ai_model').value;
            if (!apiKey) {
                resultEl.style.background = 'rgba(255,95,124,0.1)';
                resultEl.style.color = '#ff5f7c';
                resultEl.textContent = '❌ 请先填写 API Key';
                return;
            }
            try {
                const res = await fetch(`${LOCAL_API_BASE}/api/ai/test`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: apiKey, base_url: baseUrl, model })
                });
                const data = await res.json();
                if (data.status === 'success') {
                    resultEl.style.background = 'rgba(0,247,178,0.1)';
                    resultEl.style.color = '#00f7b2';
                    resultEl.textContent = '✅ 连接成功！模型响应: ' + (data.reply || 'OK').slice(0, 50);
                } else {
                    resultEl.style.background = 'rgba(255,95,124,0.1)';
                    resultEl.style.color = '#ff5f7c';
                    resultEl.textContent = '❌ 连接失败: ' + (data.message || '未知错误');
                }
            } catch(e) {
                resultEl.style.background = 'rgba(255,95,124,0.1)';
                resultEl.style.color = '#ff5f7c';
                resultEl.textContent = '❌ 连接异常: ' + e.message;
            }
        };

        function switchTab(tab) {
            ['sys', 'ai', 'ex', 'bots', 'skill'].forEach(t => {
                const btnId = t === 'skill' ? 'tabSkillBtn' : `tab${t.charAt(0).toUpperCase() + t.slice(1)}Btn`;
                const btn = document.getElementById(btnId);
                if(btn) {
                    btn.className = t === tab ? 'btn' : 'btn btn-cancel';
                    btn.style.background = t === tab ? '#00f7b2' : '';
                    btn.style.color = t === tab ? '#000' : '';
                }
                const pnl = document.getElementById(`tab-${t}`);
                if(pnl) pnl.style.display = t === tab ? 'block' : 'none';
            });
            if (tab === 'skill') loadSkillContent();
        }

        async function loadSkillContent() {
            const tid = activeTraderId || document.getElementById('activeTraderSelect')?.value;
            const label = document.getElementById('skillTraderLabel');
            if (!tid) {
                label.textContent = '未选择交易员';
                document.getElementById('skillContentEditor').value = '';
                return;
            }
            label.textContent = tid;
            try {
                const res = await fetch(`/api/traders/${tid}/skill`);
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('skillContentEditor').value = data.skill_content || '';
                }
            } catch(e) { console.warn('Load skill error:', e); }
        }

        async function saveSkillContent() {
            const tid = activeTraderId || document.getElementById('activeTraderSelect')?.value;
            if (!tid) { alert('请先选择一个交易员实例'); return; }
            const content = document.getElementById('skillContentEditor').value;
            try {
                const res = await fetch(`/api/traders/${tid}/skill`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ skill_content: content, skill_filename: 'SKILL.md' })
                });
                if (res.ok) alert('SKILL 策略已保存！');
            } catch(e) { alert('保存失败: ' + e); }
        }

        function downloadSkillFile() {
            const content = document.getElementById('skillContentEditor').value;
            if (!content) { alert('策略内容为空'); return; }
            const blob = new Blob([content], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'SKILL.md'; a.click();
            URL.revokeObjectURL(url);
        }

        function showCreateTraderForm() { document.getElementById('createTraderForm').style.display = 'block'; }
        
        function openSettingsModal() { 
            document.getElementById('settingsModal').classList.add('active'); 
            fetchSystemSettings();
            fetchTradersList();
        }
        function closeSettingsModal() { document.getElementById('settingsModal').classList.remove('active'); }

        document.getElementById('settingsForm').addEventListener('submit', async(e)=>{
            e.preventDefault();
            const formData = new FormData(e.target);
            const body = {};
            formData.forEach((val, key) => { body[key] = val; });
            await fetch('/api/system/config', {
                method:'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify(body)
            });
            fetchSystemSettings();
            alert('全局配置已保存！');
        });

        document.getElementById('newTraderForm').addEventListener('submit', async(e)=>{
            e.preventDefault();
            const formData = new FormData(e.target);
            await fetch('/api/traders', {method:'POST', body:formData});
            e.target.reset();
            document.getElementById('createTraderForm').style.display = 'none';
            fetchTradersList();
        });


        // ===== Real-time Crypto News Ticker =====
        let newsCache = [];
        async function fetchCryptoNews() {
            try {
                const res = await fetch(`${LOCAL_API_BASE}/api/news`);
                if (res.ok) {
                    const data = await res.json();
                    newsCache = data.news || [];
                    renderNewsRibbon();
                }
            } catch(e) {
                console.warn('News fetch error:', e);
            }
        }

        function renderNewsRibbon() {
            const track = document.getElementById('newsTrack');
            if (!track || newsCache.length === 0) return;

            const items = newsCache.map(n => {
                const source = n.source ? `<span class="news-tag">${escapeHtml(n.source)}</span>` : '';
                const title = escapeHtml(n.title || '');
                return `<span class="news-item">${source}<a href="${escapeHtml(n.url)}" target="_blank" rel="noopener">${title}</a></span>`;
            });
            const withSeps = [];
            items.forEach((item, i) => {
                if (i > 0) withSeps.push('<span class="news-sep">◆</span>');
                withSeps.push(item);
            });
            const segment = `<div class="news-segment">${withSeps.join('')}</div>`;
            track.innerHTML = segment + segment; // duplicate for seamless loop

            const segWidth = track.querySelector('.news-segment')?.offsetWidth || 3000;
            const speed = 40;
            const duration = segWidth / speed;
            track.style.setProperty('--news-duration', `${duration}s`);
        }

        // Init Sequence
        async function bootSequence() {
            await fetchSystemSettings();
            await fetchTradersList();
            if(document.getElementById('activeTraderSelect').value) {
                activeTraderId = document.getElementById('activeTraderSelect').value;
            }
            loadData();
            refreshStaticPanels();
            fetchCryptoNews();
            setInterval(loadData, scanFrequency);
            setInterval(fetchTradersList, 5000);
            setInterval(fetchCryptoNews, 120000); // refresh news every 2 min
        }
        
        bootSequence();