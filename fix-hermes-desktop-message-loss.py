#!/usr/bin/env python3
"""
fix-hermes-desktop-message-loss.py
==================================
One-shot fix for the Hermes Agent desktop app's "message sent but gone
after sleep/shutdown" issue.

Background
----------
By default the desktop app only writes a user message to state.db after a
full turn of ``build_turn_context`` finishes. If the machine sleeps or
shuts down before that point -- or image analysis fails, or the provider
hangs -- the message exists only in memory and vanishes on reboot (the UI
showed it as "sent", but it is gone the next morning).

What this script does:
1. tui_gateway/server.py -- persist the user message to state.db BEFORE
   calling ``run_conversation`` (the user's original text is kept, not the
   image-failure placeholder), and mark it via ``_pending_cli_user_message``
   + ``_db_persisted`` so the agent's flush skips it -- no duplicate rows.
2. run_agent.py -- stop silently skipping persistence when ``_session_db``
   is unavailable; emit an explicit warning so the reason a message was
   never persisted becomes visible.

Features
--------
- Idempotent: safe to re-run; already-patched files are skipped.
- Auto-locate: supports git installs (~/.hermes/hermes-agent) and pip.
- Safe: backs up each file before modifying (.bak.<8-hex>); on syntax
  check failure the change is rolled back.
- Zero third-party dependencies: Python standard library only.

Usage
-----
    python3 fix-hermes-desktop-message-loss.py [Hermes-install-dir]

With no argument the install dir is auto-detected. Restart the Hermes
desktop app after running.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# -------- Patch definitions --------
# Each patch: (filename, old_text, new_text, idempotent_marker)
# If the marker is already present in the file, the patch is skipped.

PATCH_RUN_AGENT_LOG = (
    "run_agent.py",
    # old: silent return
    """        if getattr(self, "_persist_disabled", False):
            return
        if not self._session_db:
            return
        # Persist user-message override (#48677 chokepoint): historically this""",
    # new: emit a warning
    """        if getattr(self, "_persist_disabled", False):
            return
        if not self._session_db:
            logger.warning(
                "Session DB unavailable for message flush (session=%s) - "
                "inbound user message is NOT persisted. This is the silent-loss "
                "path behind \\"message sent but gone after reboot\\": the agent "
                "was built without a session_db (or state.db failed to open), so "
                "turn-start persistence no-ops. Fix by passing session_db into "
                "AIAgent construction.",
                getattr(self, "session_id", None) or "none",
            )
            return
        # Persist user-message override (#48677 chokepoint): historically this""",
    'Session DB unavailable for message flush',
)

PATCH_TUI_CALLSITE = (
    "tui_gateway/server.py",
    # old: direct run_conversation call
    """            result = agent.run_conversation(run_message, **run_kwargs)""",
    # new: persist the user message first
    """            # --- Persist the user message immediately (crash-loss guard) ---
            # In the default path the user message is only written to
            # state.db at the end of build_turn_context (its
            # _ensure_and_persist step). Any failure before that point --
            # system-prompt build, preflight compression, plugin hooks,
            # memory prefetch, image analysis -- or a sleep/power cut
            # mid-turn leaves the message dangling in memory only, gone
            # after reboot. Write it here, before run_conversation is even
            # called, and hand the same dict to the turn via
            # _pending_cli_user_message (with the _db_persisted marker) so
            # the agent's _flush_messages_to_session_db skips it -- the
            # message is durable immediately and no duplicate row is made.
            # persist_user_message must equal the staged content so
            # turn_context reuses the dict (see expected_persist_content in
            # turn_context.py).
            _persist_user_message_immediately(session, agent, prompt, run_message)
            staged_content = getattr(agent, "_pending_cli_user_message", None)
            if isinstance(staged_content, dict):
                run_kwargs["persist_user_message"] = staged_content.get("content")
            result = agent.run_conversation(run_message, **run_kwargs)""",
    "_persist_user_message_immediately(session, agent, prompt, run_message)",
)

PATCH_TUI_FUNC = (
    "tui_gateway/server.py",
    # old: insert before the second _content_display_text definition
    """    return history


def _content_display_text(content: Any) -> str:
    if content is None:
        return """,
    # new: new function + original definition
    """    return history


def _persist_user_message_immediately(session: dict, agent, prompt: Any, run_message: Any) -> None:
    \"\"\"Persist the inbound user message to state.db BEFORE the turn runs.

    This is the guard against the "message sent but gone after reboot"
    class of loss: normally the user message only lands in state.db at the
    end of ``build_turn_context`` (the crash-resilience persist), so any
    interruption before that point - sleep/shutdown mid-turn, a vision
    analysis failure, a hung provider call, a plugin hook error - leaves the
    message dangling in memory only. Writing it here, before
    ``run_conversation`` is even called, makes the user's own words durable
    the instant they are accepted.

    Deduplication: the staged dict is handed to the agent as
    ``_pending_cli_user_message`` with the ``_db_persisted`` marker, so the
    agent's own flush skips it (``_flush_messages_to_session_db`` checks the
    marker) - no duplicate row, no role-alternation break.
    \"\"\"
    try:
        if getattr(agent, "_persist_disabled", False):
            return
        db = getattr(agent, "_session_db", None) or _get_db()
        if db is None:
            return
        key = session.get("session_key")
        if not key:
            return
        # The content we persist is the user's message as accepted by the
        # gateway: the plain prompt (or the multimodal parts flattened to
        # text). If image analysis failed earlier, the original prompt text
        # is still what the user actually typed - persist that, not the
        # "[The user attached an image but analysis failed.]" placeholder.
        persist_content = prompt if isinstance(prompt, str) else None
        if persist_content is None:
            # Multimodal list content: keep text parts, mark images.
            txt_parts = []
            if isinstance(run_message, list):
                for p in run_message:
                    if isinstance(p, dict) and p.get("type") == "text":
                        txt_parts.append(str(p.get("text", "")))
            persist_content = "\\n".join(txt_parts) if txt_parts else None
        if not persist_content or not persist_content.strip():
            # Nothing user-typed (image-only turn): persist a minimal marker
            # so the turn itself is still durable.
            persist_content = "[image attachment]"
        staged = {"role": "user", "content": persist_content, "_db_persisted": True}
        db.append_message(
            session_id=getattr(agent, "session_id", None) or key,
            role="user",
            content=persist_content,
        )
        # Hand the same dict to the turn so its flush skips it (marker), and
        # the loop's api_messages build finds the user message where it
        # expects it.
        agent._pending_cli_user_message = staged
        agent._persist_user_message_idx = None
        agent._persist_user_message_override = persist_content
        agent._persist_user_message_timestamp = None
    except Exception as exc:
        logger.warning(
            "Immediate user-message persist failed for session=%s: %s",
            session.get("session_key"),
            exc,
        )


def _content_display_text(content: Any) -> str:
    if content is None:
        return """,
    "def _persist_user_message_immediately(session: dict, agent, prompt: Any, run_message: Any) -> None:",
)


PATCHES = [PATCH_RUN_AGENT_LOG, PATCH_TUI_CALLSITE, PATCH_TUI_FUNC]


# -------- Helpers --------

def find_hermes_root(argv):  # -> Optional[Path]
    """Locate the Hermes install dir: explicit arg > common paths > hermes cmd."""
    # 1. Command-line argument
    for arg in argv[1:]:
        p = Path(arg).expanduser()
        if (p / "run_agent.py").exists():
            return p
    # 2. Common install locations
    home = Path.home() / ".hermes"
    candidates = [
        home / "hermes-agent",          # git install
        Path("/opt/hermes-agent"),      # common custom location
    ]
    # 3. hermes command reports its install directory
    try:
        out = subprocess.run(
            ["hermes", "--version"], capture_output=True, text=True, timeout=15
        ).stdout
        for line in out.splitlines():
            if "Install directory:" in line:
                p = Path(line.split(":", 1)[1].strip())
                if (p / "run_agent.py").exists():
                    return p
    except Exception:
        pass
    for c in candidates:
        if (c / "run_agent.py").exists():
            return c
    return None


def apply_patch(path: Path, old: str, new: str, idempotent_marker: str) -> str:
    """Apply one patch to a single file. Returns a status string."""
    text = path.read_text(encoding="utf-8")
    if idempotent_marker in text:
        return f"SKIP  already patched (idempotent marker present)"
    if old not in text:
        return f"SKIP  old code not found (version may differ; skipped)"
    backup = path.with_name(path.name + f".bak.{uuid.uuid4().hex[:8]}")
    shutil.copy2(path, backup)
    text = text.replace(old, new, 1)
    # Syntax check: roll back on failure
    tmp = Path(tempfile.mktemp(suffix=".py"))
    try:
        tmp.write_text(text, encoding="utf-8")
        import py_compile

        py_compile.compile(str(tmp), doraise=True)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return f"FAIL  syntax check failed, rolled back: {exc}"
    tmp.unlink(missing_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"OK    patched (backup: {backup.name})"


# -------- Main --------

def main() -> int:
    root = find_hermes_root(sys.argv)
    if root is None:
        print("[X] Could not locate the Hermes install directory.")
        print("   Specify it manually: python3 fix-hermes-desktop-message-loss.py /path/to/hermes-agent")
        return 1

    print(f"[DIR] Hermes install directory: {root}")
    results = []
    for fname, old, new, marker in PATCHES:
        fpath = root / fname
        if not fpath.exists():
            results.append((fname, "SKIP  file not found"))
            continue
        print(f"   {fname} ...")
        results.append((fname, apply_patch(fpath, old, new, marker)))

    print()
    print("-" * 60)
    for fname, status in results:
        print(f"  {fname:<28} {status}")

    n_ok = sum(1 for _, s in results if s.startswith("OK"))
    n_skip = sum(1 for _, s in results if s.startswith("SKIP"))
    n_fail = sum(1 for _, s in results if s.startswith("FAIL"))

    print("-" * 60)
    if n_fail == 0 and n_ok >= 0:
        print(f"[OK] Done: {n_ok} patch(es) applied, {n_skip} skipped, {n_fail} failed.")
        if n_ok > 0:
            print("[RESTART] Restart the Hermes desktop app (fully quit, then reopen) to apply the fix.")
            print("   Verify: send a message, sleep/shut down, reopen - the message should still be there.")
        else:
            print("[INFO] All patches already applied or nothing to change; restart to pick it up.")
    else:
        print(f"[WARN] {n_fail} patch(es) failed - check the output above or fix manually.")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
