"""Project / fact-graph / memory operations for the GUI.

Read-only for the truth stores from the app side (the app never fabricates a
fact ? only workers submit and the verifier gates, exactly as upstream). The app
acts as "main-agent lite": it manages projects/workers, writes PROBLEM.md,
TASK.md and master_guidance, and reads the fact graph for the operator.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from danus.core import FactGraph, GlobalMemory
from danus.execution import layout as L
from danus.execution.scaffold import atomic_write, do_new

from . import settings as S
from . import supervisor

NAME_RE = "name must match [A-Za-z0-9][A-Za-z0-9._-]*"
KIND_ORDER = ["master_guidance", "elaboration", "conclusion", "proof_attempt",
              "counterexample", "example", "dead_end", "obstacle", "direction",
              "plan", "verification"]


def _pdir(project: str) -> Path:
    pdir = L.project_dir(project)
    if not pdir.is_dir():
        raise ValueError(f"no such project: {project}")
    return pdir


def projects() -> List[Dict]:
    rows = []
    for name in L.list_projects():
        meta = {}
        mp = L.project_dir(name) / "project.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        workers = L.list_workers(name)
        live = sum(1 for w in workers
                   if supervisor._alive(supervisor._read_pid(L.WorkerLayout(L.worker_dir(name, w)))))
        fg = FactGraph(L.project_dir(name))
        rows.append({
            "name": name, "workers": len(workers), "live": live,
            "facts": len(fg.list()), "model": meta.get("model", "?"),
            "roles": meta.get("roles", ""),
        })
    return sorted(rows, key=lambda r: r["name"].lower())


def create_project(name: str, problem: str, roles: str) -> Dict:
    import re
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
        raise ValueError(NAME_RE)
    if not problem.strip():
        raise ValueError("problem statement cannot be empty")
    pdir = L.project_dir(name)
    if pdir.exists():
        raise ValueError(f"project already exists: {name}")
    # do_new scaffolds the dirs; only then write PROBLEM.md (atomic_write would
    # otherwise create the project dir first and do_new would refuse it).
    try:
        r = do_new(name, roles=roles, model=S.load().get("worker_model") or None)
    except SystemExit as e:
        raise ValueError(str(e))
    atomic_write(pdir / "PROBLEM.md",
                 f"# PROBLEM.md\n\n**Project:** `{name}`\n\n"
                 f"**Goal (verbatim).**\n\n{problem.strip()}\n")
    return {"name": name, "workers": r["workers"], "project_dir": r["project_dir"]}


def problem(project: str) -> str:
    f = _pdir(project) / "PROBLEM.md"
    return f.read_text(encoding="utf-8") if f.exists() else "(no PROBLEM.md)"


def save_problem(project: str, text: str) -> None:
    atomic_write(_pdir(project) / "PROBLEM.md", text)


def project_detail(project: str) -> Dict:
    pdir = _pdir(project)
    fg = FactGraph(pdir)
    meta = {}
    mp = pdir / "project.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    workers = [supervisor.worker_status(project, w) for w in L.list_workers(project)]
    kinds: Dict[str, int] = {}
    for k in KIND_ORDER:
        f = pdir / "global_memory" / f"{k}.jsonl"
        if f.exists():
            try:
                kinds[k] = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                kinds[k] = 0
    return {
        "name": project, "meta": meta,
        "problem": problem(project),
        "workers": workers,
        "facts_count": len(fg.list()),
        "memory_kinds": kinds,
        "deadline": _read_deadline(pdir),
        "target": _read_target(pdir),
    }


def _read_deadline(pdir: Path) -> Optional[float]:
    f = pdir / ".run_deadline"
    if not f.exists():
        return None
    try:
        return float(f.read_text().strip())
    except (ValueError, OSError):
        return None


def set_deadline(project: str, hours: Optional[float]) -> None:
    pdir = _pdir(project)
    if hours and hours > 0:
        atomic_write(pdir / ".run_deadline", str(time.time() + hours * 3600))
    else:
        (pdir / ".run_deadline").unlink(missing_ok=True)


def assign(project: str, worker: str, task: str) -> None:
    if not task.strip():
        raise ValueError("task cannot be empty")
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    if not wl.dir.is_dir():
        raise ValueError(f"no such worker: {project}/{worker}")
    atomic_write(wl.task, task if task.endswith("\n") else task + "\n")


def facts(project: str, q: str = "", limit: int = 200) -> List[Dict]:
    fg = FactGraph(_pdir(project))
    if q.strip():
        hits = fg.search(q, limit=limit)
        return [{"fact_id": h.get("fact_id"), "statement": h.get("statement"),
                 "score": h.get("score")} for h in hits]
    out = []
    for fid in fg.list()[-limit:]:
        raw = fg.get_raw(fid) or ""
        stmt = _extract_section(raw, "statement")
        out.append({"fact_id": fid, "statement": stmt[:400]})
    return sorted(out, key=lambda r: r["fact_id"])


def _extract_section(raw: str, section: str) -> str:
    marker = f"## {section}"
    if marker not in raw:
        return ""
    rest = raw.split(marker, 1)[1]
    parts = rest.split("\n## ", 1)
    return parts[0].strip()


def fact_detail(project: str, fid: str) -> Dict:
    fg = FactGraph(_pdir(project))
    if not fg.exists(fid):
        raise ValueError(f"no such fact: {fid}")
    raw = fg.get_raw(fid) or ""
    return {
        "fact_id": fid,
        "raw": raw,
        "statement": _extract_section(raw, "statement"),
        "proof": _extract_section(raw, "proof"),
        "intuition": _extract_section(raw, "intuition"),
        "predecessors": fg.predecessors(fid),
        "descendants": fg.descendants(fid),
        "external_refs": fg.external_refs(fid),
    }


def revoke(project: str, fid: str, reason: str) -> List[str]:
    if not reason.strip():
        raise ValueError("revoke needs a reason")
    fg = FactGraph(_pdir(project))
    if not fg.exists(fid):
        raise ValueError(f"no such fact: {fid}")
    return fg.revoke(fid, reason)


def terminal_facts(project: str) -> List[str]:
    """Facts nothing else depends on (candidate answers for the goal)."""
    fg = FactGraph(_pdir(project))
    used: set = set()
    for fid in fg.list():
        used.update(fg.predecessors(fid))
    return [fid for fid in fg.list() if fid not in used]


def memory(project: str, kind: str = "", limit: int = 30) -> Dict[str, List[Dict]]:
    gm = GlobalMemory(_pdir(project))
    kinds = [kind] if kind else KIND_ORDER
    out: Dict[str, List[Dict]] = {}
    for k in kinds:
        try:
            entries = gm.read(k)
        except Exception:
            entries = []
        out[k] = entries[-limit:]
    return out


def record_memory(project: str, kind: str, claim: str, evidence: str,
                  author: str = "app", **extra) -> str:
    gm = GlobalMemory(_pdir(project))
    return gm.append(kind, claim, evidence, author, verifiable=False, **extra)


def spend_log(project: str, entry: Dict) -> None:
    pdir = _pdir(project)
    f = pdir / "spend" / "consult.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

def _read_target(pdir: Path) -> Optional[Dict]:
    tf = pdir / "TARGET.md"
    if not tf.exists():
        return None
    text = tf.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"fact_id[:：]\s*([0-9a-f]{16})", text)
    fid = m.group(1) if m else None
    return {"fact_id": fid, "file": str(tf)}


def finalize(project: str, fact_id: str) -> Dict:
    """Record the operator-approved answer (the target theorem) in TARGET.md."""
    pdir = _pdir(project)
    fg = FactGraph(pdir)
    if not fg.exists(fact_id):
        raise ValueError(f"no such fact: {fact_id}")
    raw = fg.get_raw(fact_id) or ""
    stmt = _extract_section(raw, "statement")
    atomic_write(
        pdir / "TARGET.md",
        f"# TARGET\n\nproject: {project}\nfact_id: {fact_id}\n"
        f"finalized_at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"## statement\n\n{stmt}\n",
    )
    return {"fact_id": fact_id, "target_file": str(pdir / "TARGET.md")}


def dependency_closure(project: str, fact_id: str) -> List[str]:
    """All facts the target transitively depends on, ordered so every fact
    appears after the facts it cites (a topological order of the DAG)."""
    fg = FactGraph(_pdir(project))
    needed: set = set()
    stack = [fact_id]
    while stack:
        fid = stack.pop()
        if fid in needed:
            continue
        needed.add(fid)
        stack.extend(fg.predecessors(fid))
    remaining = set(needed)
    ordered: List[str] = []
    while remaining:
        ready = [fid for fid in remaining
                 if all(p not in remaining for p in fg.predecessors(fid))]
        if not ready:
            ready = [min(remaining)]  # defensive; the graph is a DAG
        ordered.extend(sorted(ready))
        remaining.difference_update(ready)
    return ordered


def write_report(project: str, fact_id: Optional[str] = None) -> Dict:
    """Assemble a readable Markdown report of the proof for the target fact."""
    pdir = _pdir(project)
    fg = FactGraph(pdir)
    if not fact_id:
        t = _read_target(pdir)
        if not t or not t.get("fact_id"):
            raise ValueError("请先在事实图里把答案事实「结题」，或传入 fact_id")
        fact_id = t["fact_id"]
    if not fg.exists(fact_id):
        raise ValueError(f"no such fact: {fact_id}")
    ordered = dependency_closure(project, fact_id)

    lines: List[str] = []
    lines.append(f"# {project} —— 证明报告")
    lines.append("")
    lines.append(f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　|　"
                 "由 DanusWin 从已验证事实图自动汇编（无需人工改写）")
    lines.append("")
    lines.append("## 1. 问题")
    lines.append("")
    lines.append(problem(project).strip())
    lines.append("")
    target_raw = fg.get_raw(fact_id) or ""
    lines.append("## 2. 结论（已通过独立验证器）")
    lines.append("")
    lines.append(f"- 答案事实编号：`{fact_id}`")
    lines.append("")
    lines.append(_extract_section(target_raw, "statement").strip())
    lines.append("")
    lines.append(f"## 3. 证明依赖的全部事实（共 {len(ordered)} 条，按依赖顺序排列）")
    lines.append("")
    for i, fid in enumerate(ordered, 1):
        raw = fg.get_raw(fid) or ""
        stmt = _extract_section(raw, "statement").strip()
        proof = _extract_section(raw, "proof").strip()
        intu = _extract_section(raw, "intuition").strip()
        preds = fg.predecessors(fid)
        lines.append(f"### {i}. 事实 `{fid}`")
        lines.append("")
        lines.append("**statement**")
        lines.append("")
        lines.append(stmt)
        lines.append("")
        lines.append("**proof**")
        lines.append("")
        lines.append(proof)
        lines.append("")
        if intu:
            lines.append("**intuition**")
            lines.append("")
            lines.append(intu)
            lines.append("")
        if preds:
            lines.append("*依赖：* " + ", ".join(f"`{p}`" for p in preds))
            lines.append("")
    lines.append("## 4. 验证说明")
    lines.append("")
    lines.append("- 本报告中每条事实都经独立的 codex 验证器判定 `correct` 后写入事实图；"
                 "证明只能引用已验证事实（fact_id），全局记忆不算数。")
    lines.append("- 验证器是基于大模型的非形式化验证（不是 Lean/Coq 机器证明），"
                 "重要结论请人工复核后再使用或发表。")
    lines.append("")
    md = "\n".join(lines)
    path = pdir / f"report_{project}.md"
    path.write_text(md, encoding="utf-8")
    return {"path": str(path), "facts": len(ordered), "md": md}