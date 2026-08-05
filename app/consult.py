"""Strategy loop (app-side): elaboration -> DeepSeek consult -> master_guidance.

This mirrors the upstream main-agent loop in Python so the GUI can steer the
swarm without Claude Code. Workers still do the proving and the stateless
verifier still gates every fact.
"""
from __future__ import annotations

import time
from typing import Dict, List

from openai import OpenAI

from . import engine, settings as S

ADVISOR_SYSTEM = (
    "You are a senior research-mathematics strategy advisor for an automated "
    "proof-search system. You receive a distilled state ('elaboration') of a "
    "mathematics project whose worker swarm proves results and a stateless "
    "verifier gates every fact. Respond with concrete strategy: the most "
    "promising decomposition(s) of the problem and the single most actionable "
    "next lemma/step per direction. Be rigorous and specific - name precise "
    "techniques, lemmas, references. Do NOT ask questions (non-interactive; "
    "resolve ambiguity yourself). Output only the strategic guidance with a "
    "numbered list of concrete directions, no preamble."
)


def _extract_reply(resp) -> str:
    """Validate a chat response; a silent empty reply must become a loud error."""
    if not getattr(resp, "choices", None):
        raise ValueError("策略咨询返回为空（无 choices）：请检查「策略咨询模型」是否支持 Chat API，或稍后重试")
    msg = resp.choices[0].message
    reply = (getattr(msg, "content", None) or "").strip()
    if not reply:
        raise ValueError("策略咨询返回空回复：请把「策略咨询模型」换成支持 Chat API 的模型（如 deepseek-v4-pro / deepseek-chat），或检查账户余额后重试")
    return reply


def _chat_reply(client, model: str, prompt: str):
    """Call the chat API; returns the raw response (validated by _extract_reply)."""
    return client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ADVISOR_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4096,
    )


def build_elaboration(project: str) -> str:
    pdir = engine._pdir(project)
    fg_problem = engine.problem(project)
    facts = engine.facts(project, limit=10)
    term = engine.terminal_facts(project)
    mem = engine.memory(project, limit=8)

    lines: List[str] = []
    lines.append("# Elaboration (auto-built by DanusWin)")
    lines.append("")
    lines.append("## 1. Goal")
    lines.append(fg_problem[:2000])
    lines.append("")
    lines.append(f"## 2. Verified fact graph: {len(engine.facts(project, limit=10**6))} facts "
                 f"(search index), {len(term)} terminal facts")
    if term:
        lines.append("Terminal facts (nothing depends on them; possible answers):")
        for fid in term[:10]:
            raw = ""
            try:
                raw = engine.fact_detail(project, fid)["statement"][:200]
            except Exception:
                pass
            lines.append(f"- `{fid}`: {raw}")
    lines.append("")
    if facts:
        lines.append("Recent facts:")
        for f in facts[-8:]:
            lines.append(f"- `{f['fact_id']}`: {f['statement'][:160]}")
        lines.append("")
    mg = mem.get("master_guidance", [])
    if mg:
        lines.append("## 3. Previous master_guidance (tail)")
        for e in mg[-2:]:
            lines.append((e.get("evidence") or e.get("claim") or "")[:1500])
        lines.append("")
    for kind, label in (("dead_end", "Dead ends"), ("obstacle", "Obstacles")):
        ents = mem.get(kind, [])
        if ents:
            lines.append(f"## 4. {label}")
            for e in ents[-5:]:
                lines.append(f"- {e.get('claim', '')[:220]}")
            lines.append("")
    ver = mem.get("verification", [])
    if ver:
        lines.append("## 5. Recent verification verdicts")
        for e in ver[-6:]:
            lines.append(f"- {e.get('claim', '')[:120]} -> {e.get('status', '?')} "
                         f"(fact_id={e.get('fact_id') or '?'})")
        lines.append("")
    lines.append("## 6. Request")
    lines.append("Give 2-4 concrete parallel directions (numbered), each with a "
                 "specific next lemma/task a single worker can attack, and one "
                 "overall priority. State which existing facts/ideas to build on.")
    return "\n".join(lines)


def consult(project: str) -> Dict:
    s = S.load()
    key = (s.get("api_key") or "").strip()
    if not key:
        raise ValueError("请先在设置页填写 DeepSeek API Key")
    base = S.effective_base(s)
    model = s.get("consult_model") or "deepseek-v4-pro"
    prompt = build_elaboration(project)
    engine.record_memory(project, "elaboration", "elaboration before consult",
                         prompt, author="app")
    client = OpenAI(api_key=key, base_url=base, timeout=180)
    t0 = time.time()
    try:
        resp = _chat_reply(client, model, prompt)
        reply = _extract_reply(resp)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"策略咨询失败（{model}）：{type(e).__name__}: {e}") from e
    claim = reply.splitlines()[0][:200] if reply else "(empty reply)"
    engine.record_memory(project, "master_guidance", claim, reply, author="app",
                         model=model, cost_usd=0.0)
    engine.spend_log(project, {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "transport": "deepseek_chat", "model": model,
        "seconds": round(time.time() - t0, 1),
        "prompt_tokens": getattr(getattr(resp, "usage", None), "prompt_tokens", 0),
        "completion_tokens": getattr(getattr(resp, "usage", None), "completion_tokens", 0),
    })
    return {"reply": reply, "model": model,
            "usage": (getattr(resp, "usage", None).model_dump()
                      if getattr(resp, "usage", None) else None),
            "seconds": round(time.time() - t0, 1),
            "guidance_id": engine.memory(project, "master_guidance", 1)
                           ["master_guidance"][-1]["id"] if engine.memory(
                project, "master_guidance", 1)["master_guidance"] else None}


def split_directions(reply: str) -> List[str]:
    """Heuristic: turn a numbered/bulleted guidance reply into per-worker tasks."""
    tasks: List[str] = []
    import re
    for line in reply.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^(\d+[.)]|[-*?])\s+", s):
            tasks.append(re.sub(r"^(\d+[.)]|[-*?])\s+", "", s).strip())
    if not tasks:
        tasks = [reply.strip()]
    return [t for t in tasks if len(t) > 8][:8]
