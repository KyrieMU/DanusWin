"""Windows-native process supervision for the verify service and worker loops.

Replaces the POSIX bash layer (services.sh / setsid / killpg) with a psutil +
subprocess implementation. The engine modules (danus.execution.loop etc.) are
unchanged ? only the launcher differs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import psutil

from danus.execution import layout as L

from . import settings as S

_verify_proc: Optional[subprocess.Popen] = None
_WINDOWS_CREATION = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
    subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def _read_json(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_pid(wl: L.WorkerLayout) -> Optional[int]:
    if not wl.pid.exists():
        return None
    try:
        return int(wl.pid.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OSError):
        return False


def _kill_tree(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
        proc.kill()
    except psutil.Error:
        pass


# --------------------------------------------------------------------------- #
# verify service                                                               #
# --------------------------------------------------------------------------- #

def verify_url() -> str:
    port = os.environ.get("VERIFY_PORT", "8091")
    return f"http://127.0.0.1:{port}"


def start_verify(s: Dict[str, str], wait: float = 45.0) -> Dict:
    global _verify_proc
    S.apply_env(s)
    if _verify_proc is not None and _verify_proc.poll() is None:
        return {"ok": True, "detail": "already running"}
    status = _health()
    if status.get("up"):
        return {"ok": True, "detail": "already running", "pid": status.get("pid")}
    S.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logf = open(S.LOG_DIR / "verify.log", "a", encoding="utf-8")
    try:
        _verify_proc = subprocess.Popen(
            [sys.executable, "-m", "danus.verify"],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            cwd=str(S.ROOT), env=os.environ.copy(),
            creationflags=_WINDOWS_CREATION,
        )
    finally:
        logf.close()
    t0 = time.time()
    while time.time() - t0 < wait:
        st = _health()
        if st.get("up"):
            return {"ok": True, "detail": "started", "pid": st.get("pid")}
        time.sleep(0.5)
    return {"ok": False, "detail": "verify service did not answer /health within "
                                   f"{wait:.0f}s (see runtime/logs/verify.log)"}


def stop_verify() -> Dict:
    global _verify_proc
    st = _health()
    if st.get("pid"):
        _kill_tree(int(st["pid"]))
    if _verify_proc is not None:
        try:
            _verify_proc.terminate()
        except Exception:
            pass
        _verify_proc = None
    return {"ok": True}


def _health() -> Dict:
    try:
        with urllib.request.urlopen(f"{verify_url()}/health", timeout=3) as r:
            body = json.loads(r.read().decode("utf-8"))
            return {"up": r.status == 200, "pid": body.get("pid"),
                    "status": body.get("status")}
    except Exception:
        return {"up": False}


def verify_status() -> Dict:
    h = _health()
    if not h.get("up"):
        return {"up": False, "detail": "down", "url": f"{verify_url()}/health"}
    return {"up": True, "pid": h.get("pid"), "status": h.get("status"),
            "url": f"{verify_url()}/health"}


# --------------------------------------------------------------------------- #
# worker loops (Windows-native start/stop, no fcntl / killpg)                  #
# --------------------------------------------------------------------------- #

def _loop_pids(project: str, worker: str) -> List[int]:
    """Find live loop processes for a worker by command line, so a second app
    instance cannot double-start a worker even if the .pid file is stale or was
    overwritten by the other instance."""
    wdir = str(L.worker_dir(project, worker)).lower()
    out: List[int] = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if not (p.info.get("name") or "").lower().startswith("python"):
                continue
            cl = p.info.get("cmdline") or []
            joined = " ".join(str(c) for c in cl).lower()
            if "danus.execution" in joined and wdir in joined:
                out.append(p.info["pid"])
        except (psutil.Error, OSError):
            continue
    return out


def start_worker(s: Dict[str, str], project: str, worker: str) -> str:
    S.apply_env(s)
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    if not wl.dir.is_dir():
        return "no-such-worker"
    if _alive(_read_pid(wl)) or _loop_pids(project, worker):
        return "already-running"
    wl.logs.mkdir(parents=True, exist_ok=True)
    wl.stop.unlink(missing_ok=True)
    logf = open(wl.logs / "loop.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "danus.execution", str(wl.dir)],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            cwd=str(wl.dir), env=os.environ.copy(),
            creationflags=_WINDOWS_CREATION,
        )
    finally:
        logf.close()
    (wl.dir / ".pid").write_text(str(proc.pid), encoding="utf-8")
    return "started"


def stop_worker(project: str, worker: str, force: bool = False) -> str:
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    pid = _read_pid(wl)
    loops = _loop_pids(project, worker)
    if not _alive(pid) and not loops:
        wl.pid.unlink(missing_ok=True)
        return "not-running"
    if not force:
        wl.stop.touch()  # graceful: the loop exits at the round boundary
        return "stopping (graceful)"
    for p in loops:
        _kill_tree(p)
    if _alive(pid):
        _kill_tree(pid)
    wl.pid.unlink(missing_ok=True)
    return "killed"


def worker_status(project: str, worker: str) -> Dict:
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    pid = _read_pid(wl)
    alive = _alive(pid)
    st = _read_json(wl.status)
    state = st.get("state", "?")
    now = time.time()
    last = st.get("last_round_at") or st.get("round_started_at") or st.get("updated_at")
    age = (now - last) if isinstance(last, (int, float)) else None
    if alive:
        rs = st.get("round_started_at")
        hard = int(os.environ.get("DANUS_ROUND_HARD_TIMEOUT", "14400"))
        if state == "running" and isinstance(rs, (int, float)) and (now - rs) > hard * 1.5:
            label = "stuck?"
        else:
            label = "working"
    else:
        label = state if state in ("stopped", "deadline", "max_rounds", "error",
                                   "terminated", "created") else "dead"
    return {
        "worker": wl.name, "pid": pid, "alive": alive, "state": state,
        "round": st.get("round", 0),
        "age_s": round(age, 1) if age is not None else None,
        "last_fact_id": st.get("last_fact_id"), "label": label,
        "error": st.get("error"),
    }


def worker_log(project: str, worker: str) -> Dict[str, str]:
    """Tail of the worker's loop log + latest round log."""
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    out: Dict[str, str] = {}
    loop_log = wl.logs / "loop.log"
    if loop_log.exists():
        out["loop"] = loop_log.read_text(encoding="utf-8", errors="replace")[-6000:]
    rounds = sorted(wl.logs.glob("round_*.log"), key=lambda p: p.name) if wl.logs.is_dir() else []
    if rounds:
        out["round"] = rounds[-1].read_text(encoding="utf-8", errors="replace")[-8000:]
        out["round_name"] = rounds[-1].name
    return out


# --------------------------------------------------------------------------- #
# worker activity (live "what is it doing" view)                              #
# --------------------------------------------------------------------------- #

_SKIP_PREFIXES = (
    "{", "}", '"', "]", "[", "---", "Plan update", "Reconnecting",
    "INFO:", "WARN ", "2026-", "```", "Reconnecting...",
)


def _curate_actions(text: str, limit: int = 8) -> List[str]:
    """Pick the most recent informative lines from a codex round log."""
    out: List[str] = []
    for ln in reversed(text.splitlines()):
        s = ln.strip()
        if not s or len(s) < 3:
            continue
        if s.startswith(_SKIP_PREFIXES):
            continue
        if s in ("codex",) or s.startswith(("success in", "failed in")):
            continue
        out.append(s[:150])
        if len(out) >= limit:
            break
    return out


def worker_activity(project: str, worker: str) -> Dict:
    """Live snapshot of what a worker is doing right now: state, latest round
    log tail, and curated recent action lines."""
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    st = _read_json(wl.status)
    rounds = sorted(wl.logs.glob("round_*.log"), key=lambda p: p.name) if wl.logs.is_dir() else []
    latest = rounds[-1] if rounds else None
    tail, actions, mtime = "", [], None
    if latest:
        try:
            text = latest.read_text(encoding="utf-8", errors="replace")
            tail = text[-500:]
            mtime = latest.stat().st_mtime
            actions = _curate_actions(text)
        except OSError:
            pass
    return {
        "worker": worker,
        "state": st.get("state", "—"),
        "round": st.get("round", 0),
        "alive": _alive(_read_pid(wl)),
        "log_mtime": mtime,
        "actions": actions,
        "tail": tail,
    }

