"""Settings, environment wiring and DeepSeek backend setup (Windows)."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import threading
from typing import Any, Dict, Optional

APP_DIR = pathlib.Path(__file__).resolve().parent
ROOT = APP_DIR.parent
RUNTIME = ROOT / "runtime"
CONFIG = ROOT / "config"
SETTINGS_FILE = CONFIG / "settings.json"
CODEX_HOME = RUNTIME / "codex-home"
VERIFY_AGENT_HOME = RUNTIME / "verify-agent"
VERIFIER_RESULTS_DIR = RUNTIME / "verify-runs"
LOG_DIR = RUNTIME / "logs"
INSTALL_LOG = LOG_DIR / "codex-install.log"

DEFAULTS: Dict[str, str] = {
    "provider": "deepseek",  # "deepseek" = 直连 DeepSeek; "opencode" = OpenCode Go 套餐
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "worker_model": "deepseek-v4-flash",
    "worker_effort": "xhigh",
    "verify_model": "deepseek-v4-flash",
    "verify_effort": "xhigh",
    "consult_model": "deepseek-v4-pro",
    "verify_port": "8091",
    "roles": "high:2,xhigh:2",
    "codex_js": "",
    "node_bin": "",
}

# Declares DeepSeek model metadata so the codex CLI accepts the model like a
# built-in (context window, reasoning efforts, tools). Written into CODEX_HOME.
MODELS_JSON = {
    "models": {
        "deepseek-v4-flash": {
            "context_window": 1048576,
            "max_output_tokens": 393216,
            "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
            "supports_tools": True,
            "vision": False,
        }
    }
}


def ensure_dirs() -> None:
    for d in (CONFIG, RUNTIME, LOG_DIR, CODEX_HOME, VERIFY_AGENT_HOME,
              VERIFIER_RESULTS_DIR, RUNTIME / "projects"):
        d.mkdir(parents=True, exist_ok=True)


def load() -> Dict[str, str]:
    ensure_dirs()
    data = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return data


def effective_base(s: Dict[str, str]) -> str:
    """Resolve the API base URL for the chosen provider (OpenCode Go vs direct)."""
    if s.get("base_url"):
        return s["base_url"].rstrip("/")
    if (s.get("provider") or "deepseek") == "opencode":
        return "https://opencode.ai/zen/go/v1"
    return "https://api.deepseek.com"


def save(s: Dict[str, str]) -> Dict[str, str]:
    ensure_dirs()
    data = dict(DEFAULTS)
    data.update({k: (v or "") for k, v in s.items() if k in DEFAULTS})
    tmp = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)
    return data


def apply_env(s: Dict[str, str]) -> None:
    """Push the app-wide env contract for every child process (workers, verify
    service, codex MCP servers). Read at CALL time by the engine modules."""
    os.environ["DANUS_ROOT"] = str(ROOT)
    os.environ["DANUS_AGENTS_ROOT"] = str(RUNTIME / "projects")
    os.environ["DANUS_VERIFY_URL"] = f"http://127.0.0.1:{s.get('verify_port') or 8091}/verify"
    os.environ["CODEX_HOME"] = str(CODEX_HOME)
    os.environ["DANUS_CODEX_MODEL"] = s.get("worker_model") or "deepseek-v4-flash"
    os.environ["DANUS_CODEX_EFFORT"] = s.get("worker_effort") or "xhigh"
    os.environ["DANUS_VERIFY_MODEL"] = s.get("verify_model") or "deepseek-v4-flash"
    os.environ["DANUS_VERIFY_EFFORT"] = s.get("verify_effort") or "xhigh"
    os.environ["VERIFY_AGENT_HOME"] = str(VERIFY_AGENT_HOME)
    os.environ["VERIFIER_RESULTS_DIR"] = str(VERIFIER_RESULTS_DIR)
    os.environ["VERIFY_PORT"] = s.get("verify_port") or "8091"
    if s.get("codex_js"):
        os.environ["DANUS_CODEX_BIN"] = s["codex_js"]
    if s.get("node_bin"):
        os.environ["DANUS_NODE"] = s["node_bin"]
    if s.get("api_key"):
        os.environ["DEEPSEEK_API_KEY"] = s["api_key"]


def detect_codex(s: Dict[str, str]) -> Dict[str, Any]:
    """Locate node + the codex CLI JS entry (npm @openai/codex)."""
    node = (s.get("node_bin") or shutil.which("node") or "").strip()
    if node and not pathlib.Path(node).exists():
        node = ""
    js = (s.get("codex_js") or "").strip()
    if js and not pathlib.Path(js).exists():
        js = ""
    if not js:
        try:
            # npm.cmd on Windows needs a shell; use the resolved path.
            npm = shutil.which("npm") or "npm"
            out = subprocess.run(f"{npm} root -g", capture_output=True,
                                 text=True, timeout=20, shell=True)
            npm_root = (out.stdout or "").strip()
            cand = pathlib.Path(npm_root) / "@openai" / "codex" / "bin" / "codex.js"
            if cand.exists():
                js = str(cand)
        except Exception:
            pass
    if not js:
        found = shutil.which("codex")
        if found:
            cand = (pathlib.Path(found).resolve().parent / "node_modules"
                    / "@openai" / "codex" / "bin" / "codex.js")
            if cand.exists():
                js = str(cand)
    return {"node_bin": node, "codex_js": js, "found": bool(js)}


def write_provider(s: Dict[str, str]) -> Dict[str, Any]:
    """Write codex provider config (DeepSeek, Responses API) + models.json into
    CODEX_HOME so workers/verifier/renderers can use DeepSeek models."""
    ensure_dirs()
    provider = (s.get("provider") or "deepseek").strip()
    if provider == "opencode":
        default_base = "https://opencode.ai/zen/go/v1"
        wire = "responses"
    else:
        default_base = "https://api.deepseek.com"
        wire = "responses"
    base = (s.get("base_url") or default_base).rstrip("/")
    cfg = (
        "# Auto-written by DanusWin. The API key is read at run time from the\n"
        "# env var DEEPSEEK_API_KEY (never stored in this file).\n"
        'model_provider = "deepseek"\n\n'
        "[model_providers.deepseek]\n"
        f'name = "DeepSeek ({s.get("worker_model")})"\n'
        f'base_url = "{base}"\n'
        'env_key = "DEEPSEEK_API_KEY"\n'
        f'wire_api = "{wire}"\n'
    )
    (CODEX_HOME / "config.toml").write_text(cfg, encoding="utf-8")
    # Prefer the official DeepSeek model catalog (schema the current codex CLI
    # understands); fall back to the minimal MODELS_JSON above.
    catalog = APP_DIR / "data" / "deepseek_models.json"
    if catalog.exists():
        (CODEX_HOME / "models.json").write_bytes(catalog.read_bytes())
    else:
        (CODEX_HOME / "models.json").write_text(
            json.dumps(MODELS_JSON, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"config": str(CODEX_HOME / "config.toml"),
            "models": str(CODEX_HOME / "models.json"),
            "base_url": base, "model": s.get("worker_model")}


def ping(s: Dict[str, str]) -> Dict[str, Any]:
    """One cheap live call against the DeepSeek endpoint (chat API, works for
    both v4-flash and v4-pro)."""
    import time
    from openai import OpenAI
    key = (s.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return {"ok": False, "error": "请先在设置里填写 DeepSeek API Key"}
    provider = (s.get("provider") or "deepseek").strip()
    if provider == "opencode":
        default_base = "https://opencode.ai/zen/go/v1"
        wire = "responses"
    else:
        default_base = "https://api.deepseek.com"
        wire = "responses"
    base = (s.get("base_url") or default_base).rstrip("/")
    model = s.get("consult_model") or "deepseek-v4-pro"
    t0 = time.time()
    try:
        client = OpenAI(api_key=key, base_url=base, timeout=40)
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=16)
        reply = (r.choices[0].message.content or "").strip()[:60]
        return {"ok": True, "model": model, "provider": provider, "base_url": base,
                "latency_s": round(time.time() - t0, 2),
                "reply": reply or "(模型无文字回复，连接本身正常)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# Codex CLI: use the latest release. Note: OpenCode Go's DeepSeek models only
# expose /v1/chat/completions, which codex >= 2026-02-01 no longer supports
# (wire_api = "chat" was removed), while 0.93.0's chat wire has a broken shell
# tool on Windows -- so for workers/verifier we use the DeepSeek direct endpoint
# (wire_api = "responses") with the latest codex CLI.
CODEX_CLI_VERSION = "latest"
_install_state = {"running": False}


def install_codex() -> bool:
    """Install @openai/codex globally via npm, in a background thread."""
    if _install_state["running"]:
        return False
    _install_state["running"] = True

    def _run() -> None:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(INSTALL_LOG, "w", encoding="utf-8") as f:
                f.write("npm install -g @openai/codex ...\n")
                f.flush()
                subprocess.run(["npm", "install", "-g", "@openai/codex"],
                               stdout=f, stderr=subprocess.STDOUT)
        finally:
            _install_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return True


def install_status() -> Dict[str, Any]:
    text = ""
    if INSTALL_LOG.exists():
        try:
            text = INSTALL_LOG.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return {"running": _install_state["running"], "log": text[-4000:]}
