#!/usr/bin/env python3
"""Cross-session memory — per-timeline journal.

Every agent run auto-appends a summary entry (user request + agent's summary
+ tool calls made). On the next run, the most recent N entries for this
timeline are injected into the agent's system prompt so it can say things like
"continuing from last session, where I cleared all filler markers..."

Additionally, the agent can explicitly `remember(key, value)` facts to pin
(e.g. "user prefers 4-second max shots"). These pinned facts are returned at
the top of the memory block and persist indefinitely.

Storage:
  ~/.resolve-ai-assistant/memory/<timeline_hash>.json
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional


MEMORY_DIR = os.path.expanduser("~/.resolve-ai-assistant/memory")
MAX_SESSIONS_IN_PROMPT = 5
MAX_TOTAL_SESSIONS = 50  # trim older entries past this


@dataclass
class SessionEntry:
    """One agent run's summary."""
    timestamp: str  # ISO
    user_request: str
    agent_summary: str
    tools_used: List[str] = field(default_factory=list)

    def to_prompt_line(self) -> str:
        # Compact form for system-prompt injection
        tools = f" ({', '.join(self.tools_used[:4])}{'...' if len(self.tools_used) > 4 else ''})" if self.tools_used else ""
        return f'- [{self.timestamp[:10]}] "{_truncate(self.user_request, 80)}" → {_truncate(self.agent_summary, 120)}{tools}'


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def _timeline_hash(timeline_name: str) -> str:
    """Stable per-timeline ID for memory file."""
    return hashlib.md5((timeline_name or "unknown").encode()).hexdigest()[:12]


def _path_for(timeline_name: str) -> str:
    os.makedirs(MEMORY_DIR, exist_ok=True)
    return os.path.join(MEMORY_DIR, f"{_timeline_hash(timeline_name)}.json")


def _load_raw(timeline_name: str) -> Dict:
    path = _path_for(timeline_name)
    if not os.path.isfile(path):
        return {"timeline_name": timeline_name, "pinned": {}, "sessions": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("pinned", {})
        data.setdefault("sessions", [])
        return data
    except Exception:
        return {"timeline_name": timeline_name, "pinned": {}, "sessions": []}


def _save_raw(timeline_name: str, data: Dict) -> None:
    path = _path_for(timeline_name)
    data["timeline_name"] = timeline_name
    # Trim to max sessions to keep file size bounded
    data["sessions"] = data.get("sessions", [])[-MAX_TOTAL_SESSIONS:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ---------- Public API ----------

def record_session(timeline_name: str, user_request: str,
                   agent_summary: str, tools_used: List[str]) -> None:
    """Append one session entry. Called after every agent run."""
    if not timeline_name:
        return
    data = _load_raw(timeline_name)
    entry = SessionEntry(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        user_request=user_request,
        agent_summary=agent_summary,
        tools_used=list(tools_used or []),
    )
    data["sessions"].append(asdict(entry))
    _save_raw(timeline_name, data)


def remember_fact(timeline_name: str, key: str, value: str) -> None:
    """Pin a key/value fact that persists indefinitely."""
    if not timeline_name or not key:
        return
    data = _load_raw(timeline_name)
    data.setdefault("pinned", {})[str(key).strip()[:60]] = str(value).strip()[:400]
    _save_raw(timeline_name, data)


def forget_fact(timeline_name: str, key: str) -> bool:
    """Remove a pinned fact. Returns True if it existed."""
    if not timeline_name or not key:
        return False
    data = _load_raw(timeline_name)
    existed = key in data.get("pinned", {})
    data.get("pinned", {}).pop(key, None)
    _save_raw(timeline_name, data)
    return existed


def recall(timeline_name: str, query: Optional[str] = None,
           max_results: int = 10) -> Dict:
    """Return pinned facts + matching session entries.

    If query is None, returns the most recent sessions. If query is given,
    returns sessions where the query substring appears in request or summary.
    """
    data = _load_raw(timeline_name)
    pinned = dict(data.get("pinned", {}))
    sessions = data.get("sessions", [])

    if query:
        q = query.lower()
        matches = [
            s for s in sessions
            if q in (s.get("user_request") or "").lower()
            or q in (s.get("agent_summary") or "").lower()
        ]
    else:
        matches = sessions[-max_results:]

    return {
        "pinned": pinned,
        "matching_sessions": matches[-max_results:],
    }


def build_memory_prompt_block(timeline_name: str) -> str:
    """Compact memory summary for injection into the agent system prompt."""
    if not timeline_name:
        return ""
    data = _load_raw(timeline_name)
    pinned = data.get("pinned", {})
    sessions = data.get("sessions", [])

    if not pinned and not sessions:
        return ""

    lines = []
    if pinned:
        lines.append("PINNED FACTS FOR THIS TIMELINE (always apply):")
        for k, v in sorted(pinned.items()):
            lines.append(f"  - {k}: {v}")

    if sessions:
        lines.append(f"\nRECENT SESSIONS (most recent last):")
        for s in sessions[-MAX_SESSIONS_IN_PROMPT:]:
            entry = SessionEntry(**{
                k: v for k, v in s.items()
                if k in {"timestamp", "user_request", "agent_summary", "tools_used"}
            })
            lines.append(entry.to_prompt_line())

    return "\n".join(lines)
