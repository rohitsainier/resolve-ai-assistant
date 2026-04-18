#!/usr/bin/env python3
"""Multi-turn tool-use agent.

Works with both Anthropic and OpenAI tool APIs. The LLM plans iteratively:
calls tools, inspects results, refines, and finishes when done.
"""

import json
import os
import time
from typing import Any, List, Optional

from agent_tools import AgentContext, TOOL_SCHEMAS, execute_tool


LOG_PATH = os.path.expanduser("~/.resolve-ai-assistant/agent.log")
MAX_TURNS = 18
MAX_TRANSCRIPT_CHARS = 30000  # trim long transcripts in system prompt


def _log(msg: str):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _detect_provider() -> str:
    from analyze import _detect_provider as dp
    return dp()


def _default_model(provider: str) -> str:
    from analyze import _default_model as dm
    return dm(provider)


# ---------- System prompt ----------

def build_system_prompt(transcript, timeline_name: str) -> str:
    tt = transcript.to_timestamped_text() if transcript else "(no transcript available)"
    if len(tt) > MAX_TRANSCRIPT_CHARS:
        tt = tt[:MAX_TRANSCRIPT_CHARS] + "\n… (truncated)"

    # Inject the active creator profile if one is set — lets the agent
    # tailor its suggestions to the editor's style.
    profile_block = ""
    try:
        from profiles import get_active_profile
        prof = get_active_profile()
        if prof:
            profile_block = f"\nACTIVE CREATOR PROFILE:\n{prof.to_prompt_summary()}\n"
    except Exception:
        pass

    # Cross-session memory — load pinned facts + recent session history
    memory_block = ""
    try:
        from memory import build_memory_prompt_block
        mb = build_memory_prompt_block(timeline_name)
        if mb:
            memory_block = f"\nMEMORY FROM PAST SESSIONS:\n{mb}\n"
    except Exception:
        pass

    return f"""You are a DaVinci Resolve editing assistant, operating on a timeline named "{timeline_name}".
{profile_block}{memory_block}

You have access to tools that can inspect the transcript, list markers, add/remove markers, build rough cuts and shorts timelines, and undo. Plan iteratively:

1. Understand the user's intent.
2. If needed, call `search_transcript` or `list_markers` first to ground your plan in real data.
3. Make edits with `add_marker`, `clear_markers`, `remove_marker`, `create_rough_cut`, or `create_shorts_timeline`.
4. When done (or if nothing to do), call `finish` with a brief summary.

Rules:
- Use timestamps from the transcript. DO NOT guess times — search first.
- Be conservative. Never make destructive edits without the user explicitly asking.
- If a request is vague, ask a clarifying question via `finish` instead of guessing.
- Prefer searching before acting. A `search_transcript` call is cheap and avoids bad placements.
- If you use a Resolve color for a marker, it must be one of: Green, Red, Blue, Yellow, Cyan, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream.
- After 12 tool calls the loop will be forcibly ended. Don't thrash.

TRANSCRIPT (timestamps are seconds from timeline start):
{tt}
"""


# ---------- Anthropic path ----------

def _run_anthropic(messages: list, system: str, model: str, ctx: AgentContext) -> str:
    from anthropic import Anthropic
    client = Anthropic()

    # Anthropic uses the schemas directly.
    tools = TOOL_SCHEMAS

    final_summary = ""
    for turn in range(MAX_TURNS):
        _log(f"[anthropic] turn {turn + 1}")
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )

        # Collect any text + tool uses
        tool_uses = []
        text_parts = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if text_parts:
            combined = "\n".join(t for t in text_parts if t.strip())
            if combined:
                ctx.emit("assistant_text", {"text": combined})

        if resp.stop_reason == "end_turn" and not tool_uses:
            return "\n".join(text_parts).strip() or "(done)"

        # Append assistant message (must include content blocks verbatim)
        messages.append({"role": "assistant", "content": resp.content})

        # Execute tool uses and send results back
        tool_result_blocks = []
        finished_via_tool = False
        for tu in tool_uses:
            name = tu.name
            args = tu.input or {}
            ctx.emit("tool_use", {"name": name, "input": args})
            _log(f"  tool_use: {name} {args}")
            if name == "finish":
                final_summary = args.get("summary", "") or "(done)"
                finished_via_tool = True
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": "OK",
                })
                continue
            result = execute_tool(ctx, name, args)
            _log(f"  result: {json.dumps(result)[:500]}")
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_result_blocks})

        if finished_via_tool:
            return final_summary

    return "(max turns reached — stopping)"


# ---------- OpenAI path ----------

def _openai_tool_schema():
    """Translate our Anthropic-style schemas to OpenAI tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOL_SCHEMAS
    ]


def _run_openai(messages: list, system: str, model: str, ctx: AgentContext) -> str:
    from openai import OpenAI
    client = OpenAI()
    tools = _openai_tool_schema()

    # OpenAI uses role=system instead of a separate field
    oai_messages = [{"role": "system", "content": system}] + messages

    final_summary = ""
    for turn in range(MAX_TURNS):
        _log(f"[openai] turn {turn + 1}")
        resp = client.chat.completions.create(
            model=model,
            messages=oai_messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.content:
            ctx.emit("assistant_text", {"text": msg.content})

        tool_calls = msg.tool_calls or []
        if not tool_calls:
            return msg.content or "(done)"

        # Record assistant message with tool_calls
        oai_messages.append({
            "role": "assistant",
            "content": msg.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        finished_via_tool = False
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            ctx.emit("tool_use", {"name": name, "input": args})
            _log(f"  tool_use: {name} {args}")
            if name == "finish":
                final_summary = args.get("summary", "") or "(done)"
                finished_via_tool = True
                result = {"ok": True}
            else:
                result = execute_tool(ctx, name, args)
            _log(f"  result: {json.dumps(result)[:500]}")
            oai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

        if finished_via_tool:
            return final_summary

    return "(max turns reached — stopping)"


# ---------- Entry point ----------

def run_agent(user_request: str, transcript, resolve, timeline,
              ui_cb=None, plan_approval_cb=None) -> dict:
    """Run the full agent loop for one user message. Returns a result dict."""
    _log(f"=== agent request: {user_request!r}")
    if not transcript or not getattr(transcript, "segments", None):
        return {
            "explanation": "No transcript available. Run Analyze first.",
            "steps": [],
        }

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()

    # Track which tools were used so we can record the session for memory.
    tools_used: list = []

    def _tool_tracking_cb(event, payload):
        if event == "tool_use":
            name = payload.get("name")
            if name and name not in tools_used and name != "finish":
                tools_used.append(name)
        if ui_cb:
            try:
                ui_cb(event, payload)
            except Exception:
                pass

    ctx = AgentContext(
        resolve=resolve,
        timeline=timeline,
        project=project,
        transcript=transcript,
        ui_cb=_tool_tracking_cb,
        plan_approval_cb=plan_approval_cb,
    )

    timeline_name = timeline.GetName() if timeline else "unknown"
    system = build_system_prompt(transcript, timeline_name)
    messages = [{"role": "user", "content": user_request}]

    provider = _detect_provider()
    model = _default_model(provider)
    _log(f"provider={provider} model={model}")

    try:
        if provider == "openai":
            summary = _run_openai(messages, system, model, ctx)
        else:
            summary = _run_anthropic(messages, system, model, ctx)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _log(f"agent crashed:\n{tb}")
        summary = f"Error: {type(e).__name__}: {e}"

    # Persist a session summary so the next run can see it.
    try:
        from memory import record_session
        record_session(timeline_name, user_request, summary, tools_used)
    except Exception as e:
        _log(f"could not record session: {e}")

    return {
        "explanation": summary,
        "undo_size": len(ctx.undo_log),
        "tools_used": tools_used,
    }
