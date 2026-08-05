"""The single shared codex launcher — one uniform CALL + env contract.

Every place Danus execs codex (the proving workers in ``danus.execution.loop``,
the verify service in ``danus.verify.launcher``, and the one-shot artifact
renderers in ``danus.authoring.driver``) resolves the codex binary, the model,
the reasoning effort, the subprocess environment, and the ``exec`` command prefix
**through this module** — so the four are uniform across the three sites and there
is exactly one place to change any of them.

All config is read at CALL time (never import time), so services stay
testable/reconfigurable.

Env contract (neutral defaults + back-compat aliases):
  DANUS_CODEX_BIN     codex binary; back-compat alias: CODEX_BIN
  DANUS_CODEX_MODEL   neutral default model (default "gpt-5.5")
  DANUS_CODEX_EFFORT  neutral default reasoning effort (default "xhigh")

Each site layers its own per-service override env names on top of the neutral
defaults via ``model(*overrides)`` / ``effort(*overrides)`` (e.g. the verify
service passes ``DANUS_VERIFY_MODEL``; the renderers pass
``DANUS_WRITE_PAPER_MODEL`` / ``DANUS_HUMAN_SUMMARY_MODEL``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# danus/codex.py → repo root is one parent up; the deployment's bin/codex wrapper
# lives at <repo>/bin/codex.
_REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODEL = "gpt-5.5"
DEFAULT_EFFORT = "xhigh"


def resolve_bin() -> str:
    """Resolve the codex binary at CALL time. Precedence:
      1. ``DANUS_CODEX_BIN`` env,
      2. ``<repo>/bin/codex`` wrapper if it exists,
      3. ``shutil.which("codex")``,
      4. the bare string ``"codex"`` (so a missing binary raises a clear
         FileNotFoundError at exec time, not import time).
    """
    override = os.environ.get("DANUS_CODEX_BIN")
    if override:
        # An absolute override is used as-is; a bare/relative name is resolved to
        # its absolute path via PATH so subprocess_env can prepend its dir for the
        # codex ``#!/usr/bin/env node`` shebang. Fall back to the raw override if
        # it is not on PATH (exec then surfaces a clear FileNotFoundError).
        if os.path.isabs(override):
            return override
        return shutil.which(override) or override
    wrapper = _REPO_ROOT / "bin" / "codex"
    if wrapper.exists():
        return str(wrapper)
    # Windows: prefer the npm-installed JS entry over an arbitrary "codex" on
    # PATH (the Windows Store app ships a codex.exe that cannot run as a CLI).
    if os.name == "nt":
        npm_js = _npm_codex_js()
        if npm_js:
            return str(npm_js)
    which = shutil.which("codex")
    if which:
        return which
    return "codex"


def _npm_codex_js() -> Optional[Path]:
    """Locate the real Codex CLI entry from the npm global root."""
    try:
        npm = shutil.which("npm") or "npm"  # npm.cmd on Windows: needs a shell
        out = subprocess.run(f"{npm} root -g", capture_output=True,
                             text=True, timeout=20, shell=True)
        npm_root = (out.stdout or "").strip()
        if npm_root:
            cand = Path(npm_root) / "@openai" / "codex" / "bin" / "codex.js"
            if cand.exists():
                return cand
    except Exception:
        pass
    return None


def _node_bin() -> str:
    """Windows adaptation: the codex CLI is a Node program; resolve the node
    executable that must be prepended to run a ``codex.js`` directly."""
    env_node = os.environ.get("DANUS_NODE")
    if env_node:
        return env_node
    return shutil.which("node") or "node"


def model(*override_env_names: str, default: str = DEFAULT_MODEL) -> str:
    """The codex model: first non-empty among the given per-service override env
    vars (in order), then the neutral ``DANUS_CODEX_MODEL``, then ``default``."""
    for name in override_env_names:
        val = os.environ.get(name)
        if val:
            return val
    return os.environ.get("DANUS_CODEX_MODEL") or default


def effort(*override_env_names: str, default: str = DEFAULT_EFFORT) -> str:
    """The reasoning effort: first non-empty among the given per-service override
    env vars (in order), then the neutral ``DANUS_CODEX_EFFORT``, then
    ``default``."""
    for name in override_env_names:
        val = os.environ.get(name)
        if val:
            return val
    return os.environ.get("DANUS_CODEX_EFFORT") or default


def subprocess_env(codex_bin: str) -> Dict[str, str]:
    """A copy of ``os.environ`` with the codex binary's DIR prepended to ``PATH``
    so its ``#!/usr/bin/env node`` shebang resolves regardless of how the caller
    was launched.

    Only augments PATH when ``codex_bin`` has a directory component (a concrete
    path); the bare ``"codex"`` fallback must NOT inject the CWD into the
    subprocess PATH.
    """
    env = os.environ.copy()
    if os.path.dirname(codex_bin):
        codex_dir = os.path.dirname(os.path.abspath(codex_bin))
        if codex_dir and codex_dir != ".":
            existing = env.get("PATH", "")
            parts = existing.split(os.pathsep) if existing else []
            if codex_dir not in parts:
                env["PATH"] = codex_dir + (os.pathsep + existing if existing else "")
    return env


def exec_cmd(codex_bin: str, model: str, effort: str, *tail: str) -> List[str]:
    """The uniform ``codex exec`` command prefix + the caller's exact tail.

    Standardizes on the QUOTED reasoning-effort config form
    (``model_reasoning_effort="<effort>"``). The ``*tail`` is passed through
    verbatim (each site keeps its own exact tail: sandbox flags, ``-C`` home,
    MCP ``-c`` injection, output path, the ``-`` stdin sentinel, the prompt, …).
    """
    args = [
        "--model", model,
        "--config", f'model_reasoning_effort="{effort}"',
        *tail,
    ]
    if os.name == "nt":
        if codex_bin.lower().endswith(".js"):
            return [_node_bin(), codex_bin, "exec", *args]
        resolved = shutil.which(codex_bin)
        if resolved and resolved.lower().endswith((".cmd", ".bat")):
            js = (Path(resolved).resolve().parent
                  / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")
            if js.exists():
                return [_node_bin(), str(js), "exec", *args]
            # a user-supplied .cmd/.bat wrapper without an npm codex.js sibling:
            # run it through cmd.exe so CreateProcess can start it
            comspec = os.environ.get("COMSPEC") or "cmd.exe"
            return [comspec, "/d", "/c", resolved, "exec", *args]
        if codex_bin.lower().endswith(".py"):
            # a python-script codex wrapper (test stubs, custom backends): run it
            # with the current interpreter instead of relying on a shebang
            return [sys.executable, codex_bin, "exec", *args]
    return [codex_bin, "exec", *args]
