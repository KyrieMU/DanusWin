"""DanusWin ? FastAPI backend + REST API for the GUI."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import consult, engine, settings as S, supervisor

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="DanusWin", version="0.1.0")
_lock = threading.Lock()

# settings cache (loaded at startup, refreshed on PUT)
_state: Dict[str, Any] = {"settings": dict(S.DEFAULTS)}


def _settings() -> Dict[str, str]:
    return _state["settings"]


# --------------------------------------------------------------------------- #
# models                                                                       #
# --------------------------------------------------------------------------- #

class SettingsBody(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    worker_model: str = "deepseek-v4-flash"
    worker_effort: str = "xhigh"
    verify_model: str = "deepseek-v4-flash"
    verify_effort: str = "xhigh"
    consult_model: str = "deepseek-v4-pro"
    verify_port: str = "8091"
    roles: str = "high:2,xhigh:2"
    codex_js: str = ""
    node_bin: str = ""


class ProjectBody(BaseModel):
    name: str
    problem: str
    roles: str = "high:2,xhigh:2"


class ProblemBody(BaseModel):
    problem: str


class TaskBody(BaseModel):
    task: str


class StopBody(BaseModel):
    force: bool = False


class RevokeBody(BaseModel):
    reason: str


class FinalizeBody(BaseModel):
    fact_id: str


class AssignBody(BaseModel):
    tasks: List[str] = []
    split: bool = False


# --------------------------------------------------------------------------- #
# startup                                                                      #
# --------------------------------------------------------------------------- #

@app.on_event("startup")
def _startup() -> None:
    S.ensure_dirs()
    _state["settings"] = S.load()
    S.apply_env(_state["settings"])
    # Auto-start the verify service (no verify -> no facts).
    try:
        supervisor.start_verify(_state["settings"], wait=10.0)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# system / settings                                                            #
# --------------------------------------------------------------------------- #

@app.get("/api/overview")
def overview() -> Dict[str, Any]:
    s = _settings()
    codex = S.detect_codex(s)
    return {
        "verify": supervisor.verify_status(),
        "codex": codex,
        "projects": engine.projects(),
        "settings": {k: v for k, v in s.items() if k != "api_key"},
        "has_key": bool(s.get("api_key")),
        "version": "0.1.0",
    }


@app.get("/api/settings")
def get_settings() -> Dict[str, str]:
    return _settings()


@app.put("/api/settings")
def put_settings(body: SettingsBody) -> Dict[str, str]:
    data = body.model_dump()
    _state["settings"] = S.save(data)
    S.apply_env(_state["settings"])
    return _state["settings"]


@app.post("/api/setup/detect")
def setup_detect() -> Dict[str, Any]:
    d = S.detect_codex(_settings())
    if d.get("codex_js"):
        _state["settings"] = S.save({**_settings(), **d})
    return d


@app.post("/api/setup/write-provider")
def setup_write_provider() -> Dict[str, Any]:
    s = _settings()
    if not s.get("api_key"):
        raise HTTPException(400, "请先填写 DeepSeek API Key")
    return S.write_provider(s)


@app.post("/api/setup/ping")
def setup_ping() -> Dict[str, Any]:
    return S.ping(_settings())


@app.post("/api/setup/install-codex")
def setup_install_codex() -> Dict[str, Any]:
    return {"started": S.install_codex()}


@app.get("/api/setup/install-status")
def setup_install_status() -> Dict[str, Any]:
    return S.install_status()


# --------------------------------------------------------------------------- #
# verify service                                                               #
# --------------------------------------------------------------------------- #

@app.post("/api/verify/start")
def verify_start() -> Dict[str, Any]:
    with _lock:
        return supervisor.start_verify(_settings())


@app.post("/api/verify/stop")
def verify_stop() -> Dict[str, Any]:
    with _lock:
        return supervisor.stop_verify()


@app.get("/api/verify/status")
def verify_status() -> Dict[str, Any]:
    return supervisor.verify_status()


# --------------------------------------------------------------------------- #
# projects                                                                     #
# --------------------------------------------------------------------------- #

@app.get("/api/projects")
def api_projects() -> List[Dict]:
    return engine.projects()


@app.post("/api/projects")
def api_create_project(body: ProjectBody) -> Dict:
    try:
        return engine.create_project(body.name, body.problem, body.roles)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{project}")
def api_project(project: str) -> Dict:
    try:
        return engine.project_detail(project)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.put("/api/projects/{project}/problem")
def api_save_problem(project: str, body: ProblemBody) -> Dict:
    try:
        engine.save_problem(project, body.problem)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/projects/{project}/deadline")
def api_set_deadline(project: str, body: Optional[Dict] = None) -> Dict:
    body = body or {}
    hours = body.get("hours")
    try:
        engine.set_deadline(project, hours)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(404, str(e))


# --------------------------------------------------------------------------- #
# workers                                                                      #
# --------------------------------------------------------------------------- #

@app.post("/api/projects/{project}/workers/start")
def api_workers_start(project: str) -> Dict:
    s = _settings()
    with _lock:
        results = {}
        for w in engine.project_detail(project)["workers"]:
            name = w["worker"]
            results[name] = supervisor.start_worker(s, project, name)
        return {"results": results}


@app.post("/api/projects/{project}/workers/stop")
def api_workers_stop(project: str, body: StopBody) -> Dict:
    with _lock:
        results = {}
        for w in engine.project_detail(project)["workers"]:
            name = w["worker"]
            results[name] = supervisor.stop_worker(project, name, force=body.force)
        return {"results": results}


@app.put("/api/projects/{project}/workers/{worker}/task")
def api_assign_task(project: str, worker: str, body: TaskBody) -> Dict:
    try:
        engine.assign(project, worker, body.task)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{project}/workers/{worker}/log")
def api_worker_log(project: str, worker: str) -> Dict[str, str]:
    return supervisor.worker_log(project, worker)


# --------------------------------------------------------------------------- #
# strategy                                                                     #
# --------------------------------------------------------------------------- #

@app.post("/api/projects/{project}/strategy/consult")
def api_strategy_consult(project: str) -> Dict:
    try:
        return consult.consult(project)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"策略咨询失败：{e}")


@app.get("/api/projects/{project}/strategy/guidance")
def api_strategy_guidance(project: str) -> Dict:
    mem = engine.memory(project, "master_guidance", 3)
    return {"entries": mem.get("master_guidance", [])}


@app.post("/api/projects/{project}/strategy/assign")
def api_strategy_assign(project: str, body: AssignBody) -> Dict:
    detail = engine.project_detail(project)
    workers = [w["worker"] for w in detail["workers"]]
    if not workers:
        raise HTTPException(400, "项目里没有 worker")
    tasks = body.tasks
    if body.split and not tasks:
        g = engine.memory(project, "master_guidance", 1).get("master_guidance", [])
        if not g:
            raise HTTPException(400, "还没有 master_guidance，先生成策略指引")
        tasks = consult.split_directions(g[-1].get("evidence", ""))
    if not tasks:
        raise HTTPException(400, "没有可分配的任务")
    results = {}
    for i, w in enumerate(workers):
        task = tasks[i % len(tasks)]
        results[w] = task
        try:
            engine.assign(project, w, f"# ??????? master_guidance?\n\n{task}")
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"results": results, "tasks": tasks}


# --------------------------------------------------------------------------- #
# fact graph / memory                                                          #
# --------------------------------------------------------------------------- #

@app.get("/api/projects/{project}/facts")
def api_facts(project: str, q: str = "", limit: int = 200) -> List[Dict]:
    try:
        return engine.facts(project, q, limit)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/projects/{project}/facts/{fid}")
def api_fact(project: str, fid: str) -> Dict:
    try:
        return engine.fact_detail(project, fid)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/projects/{project}/facts/{fid}/revoke")
def api_revoke(project: str, fid: str, body: RevokeBody) -> Dict:
    try:
        revoked = engine.revoke(project, fid, body.reason)
        return {"ok": True, "revoked": revoked}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{project}/terminal")
def api_terminal(project: str) -> List[Dict]:
    try:
        fg_ids = engine.terminal_facts(project)
        out = []
        for fid in fg_ids:
            d = engine.fact_detail(project, fid)
            out.append({"fact_id": fid, "statement": d["statement"][:300]})
        return out
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/projects/{project}/finalize")
def api_finalize(project: str, body: FinalizeBody) -> Dict:
    try:
        return engine.finalize(project, body.fact_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{project}/report")
def api_report(project: str, body: Dict = Body(default={})) -> Dict:
    try:
        return engine.write_report(project, body.get("fact_id"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{project}/report/download")
def api_report_download(project: str) -> FileResponse:
    try:
        pdir = engine._pdir(project)
    except ValueError as e:
        raise HTTPException(404, str(e))
    files = sorted(pdir.glob("report_*.md"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(404, "还没有报告：先在事实图里打开答案事实，点「结题」再「导出 MD 报告」")
    return FileResponse(files[0], filename=files[0].name)


@app.get("/api/projects/{project}/activity")
def api_activity(project: str) -> Dict:
    try:
        engine._pdir(project)
    except ValueError as e:
        raise HTTPException(404, str(e))
    out = {}
    for w in engine.project_detail(project)["workers"]:
        name = w["worker"]
        out[name] = supervisor.worker_activity(project, name)
    return out


@app.get("/api/projects/{project}/memory")
def api_memory(project: str, kind: str = "", limit: int = 30) -> Dict:
    try:
        return engine.memory(project, kind, limit)
    except ValueError as e:
        raise HTTPException(404, str(e))


# --------------------------------------------------------------------------- #
# static UI                                                                    #
# --------------------------------------------------------------------------- #

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
