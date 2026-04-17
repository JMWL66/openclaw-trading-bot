from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import requests as py_requests
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__, static_folder="../public", static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}})

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = BASE_DIR / "public" / "index.html"
SYSTEM_CONFIG_FILE = BASE_DIR / "data" / "system_config.json"
SESSIONS_DIR = BASE_DIR / "data" / "sessions"

# In-memory track of running Popen objects
# format: { "trader_id": <Popen> }
active_processes = {}
process_lock = threading.Lock()

def get_system_config() -> dict[str, Any]:
    try:
        if SYSTEM_CONFIG_FILE.exists():
            return json.loads(SYSTEM_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "ai_providers": {},
        "exchanges": {},
        "traders": {},
        "web_title": "OKX AI Trading Challenge",
        "web_brand": "OpenClaw",
    }

def save_system_config(config: dict[str, Any]):
    SYSTEM_CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_optional_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    number = float(text)
    if number <= 0:
        raise ValueError("初始交易金额必须大于 0")
    return number


def _sync_trader_status_start_balance(trader_id: str, initial_balance: float | None):
    if initial_balance is None:
        return
    status_file = SESSIONS_DIR / trader_id / "status.json"
    if not status_file.exists():
        return
    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
        current_equity = float(status.get("equity", status.get("balance", 0)) or 0)
        status["start_balance"] = initial_balance
        status["yield_rate"] = round(
            (current_equity - initial_balance) / initial_balance if initial_balance > 0 else 0,
            6,
        )
        status["total_profit"] = round(current_equity - initial_balance, 2)
        status_file.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _pid_is_running(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_pid(pid: Any, timeout: float = 2.0) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return True
    if pid_int <= 0:
        return True
    try:
        os.kill(pid_int, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_is_running(pid_int):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid_int, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return not _pid_is_running(pid_int)


def _refresh_trader_statuses(config: dict[str, Any]) -> dict[str, Any]:
    traders = config.get("traders", {})
    changed = False
    with process_lock:
        for tid, tinfo in traders.items():
            proc = active_processes.get(tid)
            is_running = False
            if proc is not None:
                if proc.poll() is None:
                    is_running = True
                    if tinfo.get("pid") != proc.pid:
                        tinfo["pid"] = proc.pid
                        changed = True
                else:
                    del active_processes[tid]
            elif _pid_is_running(tinfo.get("pid")):
                is_running = True
            else:
                if tinfo.pop("pid", None) is not None:
                    changed = True

            next_status = "running" if is_running else "stopped"
            if tinfo.get("status") != next_status:
                tinfo["status"] = next_status
                changed = True
    if changed:
        save_system_config(config)
    return traders


@app.after_request
def add_no_store_headers(response):
    if (
        request.path.startswith("/data/")
        or request.path.startswith("/api/")
        or request.path.startswith("/js/")
        or request.path.startswith("/css/")
        or request.path in {"/", "/index.html"}
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/", methods=["GET"])
@app.route("/index.html", methods=["GET"])
def index():
    return send_file(INDEX_FILE)


@app.route("/api/system/config", methods=["GET"])
def get_config():
    config = get_system_config()
    _refresh_trader_statuses(config)
    return jsonify(config), 200

@app.route("/api/system/config", methods=["POST"])
def update_config():
    try:
        config = get_system_config()
        if request.is_json:
            updates = request.json
        else:
            updates = request.form.to_dict()
            
        if "web_title" in updates:
            config["web_title"] = updates["web_title"]
        if "web_brand" in updates:
            config["web_brand"] = updates["web_brand"]
        if "ai_providers" in updates:
            config["ai_providers"] = updates["ai_providers"]
        if "exchanges" in updates:
            config["exchanges"] = updates["exchanges"]
            
        save_system_config(config)
        return jsonify({"status": "success", "config": config}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

@app.route("/api/traders", methods=["GET"])
def list_traders():
    config = get_system_config()
    traders = _refresh_trader_statuses(config)

    return jsonify({"traders": traders}), 200

@app.route("/api/traders", methods=["POST"])
def create_or_update_trader():
    try:
        config = get_system_config()
        traders = config.setdefault("traders", {})
        
        req_data = request.json if request.is_json else request.form.to_dict()
        tid = req_data.get("id") or f"trader_{int(time.time()*1000)}"
        
        trader_info = traders.get(tid, {"status": "stopped"})
        trader_info.update({
            "name": req_data.get("name", trader_info.get("name", tid)),
            "exchange": req_data.get("exchange", trader_info.get("exchange", "")),
            "ai_provider": req_data.get("ai_provider", trader_info.get("ai_provider", "")),
            "scan_frequency": req_data.get("scan_frequency", trader_info.get("scan_frequency", 15)),
        })

        initial_balance = _parse_optional_positive_float(req_data.get("initial_balance"))
        if initial_balance is None:
            trader_info.pop("initial_balance", None)
        else:
            trader_info["initial_balance"] = initial_balance
        
        # File upload support
        if "skill_file" in request.files:
            file = request.files["skill_file"]
            if file.filename:
                content = file.read().decode("utf-8", errors="replace")
                trader_info["skill_content"] = content
                trader_info["skill_filename"] = file.filename
        elif "skill_content" in req_data:
            trader_info["skill_content"] = req_data["skill_content"]
            trader_info["skill_filename"] = req_data.get("skill_filename", "custom_skill.txt")
            
        traders[tid] = trader_info
        save_system_config(config)
        _sync_trader_status_start_balance(tid, initial_balance)
        return jsonify({"status": "success", "traders": traders}), 200
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

@app.route("/api/traders/<trader_id>", methods=["DELETE"])
def delete_trader(trader_id: str):
    config = get_system_config()
    with process_lock:
        proc = active_processes.get(trader_id)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            del active_processes[trader_id]
            
    if trader_id in config.get("traders", {}):
        del config["traders"][trader_id]
        save_system_config(config)
        
    return jsonify({"status": "success"}), 200

@app.route("/api/traders/<trader_id>/start", methods=["POST"])
def start_trader(trader_id: str):
    config = get_system_config()
    traders = config.get("traders", {})
    if trader_id not in traders:
        return jsonify({"status": "error", "message": "Trader not found"}), 404
        
    with process_lock:
        proc = active_processes.get(trader_id)
        if proc and proc.poll() is None:
            return jsonify({"status": "already_running"}), 200
        existing_pid = traders[trader_id].get("pid")
        if _pid_is_running(existing_pid):
            traders[trader_id]["status"] = "running"
            save_system_config(config)
            return jsonify({"status": "already_running", "pid": int(existing_pid)}), 200
            
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        session_dir = SESSIONS_DIR / trader_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = session_dir / "engine.log"
        f = open(log_file, "ab")
        
        python_cmd = os.getenv("PYTHON_CMD", "python3")
        script_path = BASE_DIR / "src" / "ai_trader.py"
        
        if not script_path.exists():
            return jsonify({"status": "error", "message": "ai_trader.py not found!"}), 500

        # Build environment with OKX + MiniMax credentials
        env = os.environ.copy()
        # Ensure node/okx CLI are discoverable in subprocess
        home = Path.home()
        extra_paths = [
            str(home / ".local" / "bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]
        env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "/usr/bin:/bin")
        exchange_id = traders[trader_id].get("exchange", "")
        exchange_cfg = config.get("exchanges", {}).get(exchange_id, {})
        if exchange_cfg:
            env["OKX_API_KEY"] = exchange_cfg.get("api_key", "")
            env["OKX_SECRET_KEY"] = exchange_cfg.get("secret_key", "")
            env["OKX_PASSPHRASE"] = exchange_cfg.get("passphrase", "")
            if exchange_cfg.get("is_demo"):
                env["OKX_DEMO"] = "1"
            if exchange_cfg.get("competition_mode"):
                env["OKX_COMPETITION_MODE"] = "1"

        ai_id = traders[trader_id].get("ai_provider", "")
        ai_cfg = config.get("ai_providers", {}).get(ai_id, {})
        if ai_cfg:
            env["MINIMAX_API_KEY"] = ai_cfg.get("api_key", "")
            env["MINIMAX_MODEL"] = ai_cfg.get("model", "MiniMax-M2.7")
            env["MINIMAX_BASE_URL"] = ai_cfg.get("base_url", "https://api.minimax.io/v1")

        p = subprocess.Popen(
            [python_cmd, str(script_path), "--trader_id", trader_id],
            cwd=BASE_DIR,
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        active_processes[trader_id] = p
        
        traders[trader_id]["status"] = "running"
        traders[trader_id]["pid"] = p.pid
        save_system_config(config)
        
    return jsonify({"status": "started", "pid": p.pid}), 200

@app.route("/api/traders/<trader_id>/stop", methods=["POST"])
def stop_trader(trader_id: str):
    config = get_system_config()
    with process_lock:
        proc = active_processes.get(trader_id)
        pid = config.get("traders", {}).get(trader_id, {}).get("pid")
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            del active_processes[trader_id]
        elif _pid_is_running(pid):
            _stop_pid(pid)
        else:
            if trader_id in config.get("traders", {}):
                config["traders"][trader_id]["status"] = "stopped"
                config["traders"][trader_id].pop("pid", None)
                save_system_config(config)
            return jsonify({"status": "already_stopped"}), 200
            
    if trader_id in config.get("traders", {}):
        config["traders"][trader_id]["status"] = "stopped"
        config["traders"][trader_id].pop("pid", None)
        save_system_config(config)
        
    return jsonify({"status": "stopped"}), 200


@app.route("/api/traders/<trader_id>/skill", methods=["GET"])
def get_skill(trader_id: str):
    config = get_system_config()
    trader = config.get("traders", {}).get(trader_id)
    if not trader:
        return jsonify({"error": "Trader not found"}), 404
    content = trader.get("skill_content", "")
    if not content:
        skill_file = BASE_DIR / "docs" / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text(encoding="utf-8")
    return jsonify({"skill_content": content, "skill_filename": trader.get("skill_filename", "SKILL.md")}), 200


@app.route("/api/traders/<trader_id>/skill", methods=["POST"])
def update_skill(trader_id: str):
    config = get_system_config()
    traders = config.get("traders", {})
    if trader_id not in traders:
        return jsonify({"error": "Trader not found"}), 404
    data = request.json if request.is_json else request.form.to_dict()
    traders[trader_id]["skill_content"] = data.get("skill_content", "")
    traders[trader_id]["skill_filename"] = data.get("skill_filename", "SKILL.md")
    save_system_config(config)
    return jsonify({"status": "success"}), 200


@app.route("/data/<trader_id>/<filename>", methods=["GET"])
def get_trader_data(trader_id: str, filename: str):
    if filename in {"status.json", "thinking.json", "trades.json"}:
        path = SESSIONS_DIR / trader_id / filename
        if path.exists():
            return send_file(path)
        # return empty state if not started yet
        if filename == "status.json":
            return jsonify({"balance": 0, "equity": 0, "unrealized_pnl": 0, "events": [], "equity_history": []})
        return jsonify([])
    return jsonify({"error": "File not found"}), 404


@app.route("/api/ai/test", methods=["POST"])
def test_ai_connection():
    """Proxy AI test request to avoid CORS issues with direct browser calls."""
    try:
        data = request.json or {}
        api_key = data.get("api_key", "")
        base_url = data.get("base_url", "https://api.minimax.io/v1")
        model = data.get("model", "MiniMax-M2.7")
        if not api_key:
            return jsonify({"status": "error", "message": "缺少 API Key"}), 400

        resp = py_requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Hi, reply with just OK"}],
                "max_tokens": 10,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            reply = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "OK")
            return jsonify({"status": "success", "reply": reply[:100]}), 200
        else:
            return jsonify({"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/news", methods=["GET"])
def get_crypto_news():
    """Fetch latest crypto news from CoinDesk RSS (via rss2json, free, no key needed)."""
    try:
        resp = py_requests.get(
            "https://api.rss2json.com/v1/api.json?rss_url=https://www.coindesk.com/arc/outboundfeeds/rss/",
            timeout=8,
        )
        if resp.status_code == 200:
            articles = resp.json().get("items", [])[:15]
            news = [
                {
                    "title": a.get("title", ""),
                    "source": "CoinDesk",
                    "url": a.get("link", ""),
                    "published": a.get("pubDate", ""),
                }
                for a in articles
            ]
            return jsonify({"news": news}), 200
        return jsonify({"news": []}), 200
    except Exception:
        return jsonify({"news": []}), 200


if __name__ == "__main__":
    print("启动 OpenClaw 轻量级多交易员引擎及监控面板...")
    print("Dashboard: http://127.0.0.1:5000")
    # Clean up sync status locally
    config = get_system_config()
    for tid, tinfo in config.get("traders", {}).items():
        tinfo["status"] = "stopped"
    save_system_config(config)
    
    app.run(host="127.0.0.1", port=5000)
