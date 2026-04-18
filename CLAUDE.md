# CLAUDE.md

Guidance for Claude Code sessions working in this repo.

## What this is

A DaVinci Resolve plugin that transcribes the active timeline, runs an LLM over the transcript, and edits the timeline (markers, rough cuts, shorts timelines, chapters, subtitles). UI is a local web app served from the script itself and opened in the user's default browser.

Forked from `Kilo-Loco/resolve-ai-assistant`. Substantial rewrite on top of the original Fusion-UI base.

## Project layout

```
src/
  ai_edit_assistant.py  # entry point — Resolve launches this via a tiny wrapper
  web_server.py         # stdlib http.server, serves web/index.html + JSON API
  web/index.html        # the actual UI (HTML + CSS + vanilla JS)
  prompt_editor.py      # natural-language editing (JSON action plan + execute)
  transcribe.py         # ffmpeg audio extract + Whisper, progress reporting
  analyze.py            # llm_complete() provider abstraction, chapter/filler analyzers
  markers.py            # apply_markers, clear_markers, rough_cut, shorts_timeline
  env_loader.py         # minimal .env loader (no python-dotenv dep)
  cli.py                # standalone CLI — transcribe/analyze/apply/subtitles/rough-cut/shorts-timeline
  tk_ui.py              # legacy Tkinter UI (not used in current main() — kept as reference)
install.sh              # writes a tiny launcher to Resolve's Fusion/Scripts/Edit/
```

## Runtime environment

This project runs in **two Pythons** and they have different constraints:

### In-Resolve (where `main()` runs)
- Resolve 20 (non-App-Store, non-sandboxed) only accepts **python.org Python 3.11** installed at `/Library/Frameworks/Python.framework/Versions/3.11/`. Not conda, not Homebrew, not system.
- Resolve injects `fusion` as a global — but it's a `PyRemoteObject` (`FusionUI`) whose `.UIManager` is `None` in Resolve Free. Don't rely on Fusion UI.
- `sys.executable` returns the Resolve binary itself (Resolve embeds Python via `libpython3.11.dylib`).
- `stdout`/`stderr` are captured and aren't a real TTY. Any library that `write()`s to them can raise `SystemError: <built-in function write> returned a result with an exception set`. **Always wrap third-party calls that might print (whisper, torch, tqdm) in `contextlib.redirect_stdout(devnull)`**.
- `PATH` is stripped. Shell out via absolute paths or set `os.environ["PATH"]` before calling libs that bare-call binaries (whisper bare-calls `ffmpeg`).
- `DaVinciResolveScript` module isn't on `sys.path` by default; the launcher adds `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules`.

### CLI / standalone (any Python)
- conda env with `python=3.11` is fine
- Same `requirements.txt` works
- `env_loader` picks up `.env` files

## The launcher

`install.sh` writes this tiny wrapper to Resolve's scripts dir:

```python
# Make DaVinciResolveScript importable
RESOLVE_API = "/Library/Application Support/.../Developer/Scripting"
os.environ.setdefault("RESOLVE_SCRIPT_API", RESOLVE_API)
sys.path.insert(0, os.path.join(RESOLVE_API, "Modules"))

# Point at repo source
sys.path.insert(0, REPO_SRC)

# Read UTF-8 (default is ASCII in Resolve's captured Python — emojis break it)
with open(SCRIPT_PATH, "rb") as f:
    code = compile(f.read().decode("utf-8"), SCRIPT_PATH, "exec")

# exec with current globals so Resolve-injected `fusion` propagates
g = globals().copy()
g["__file__"] = SCRIPT_PATH
g["__name__"] = "__main__"
exec(code, g)
```

Key points:
- **Must read source as bytes + decode utf-8 explicitly** (Resolve's Python defaults to ASCII)
- **Must use `exec(code, globals)` not `runpy.run_path`** — runpy creates a fresh namespace and drops `fusion`
- **Must set `RESOLVE_SCRIPT_API` + sys.path before importing DaVinciResolveScript**
- **Launcher is NOT a symlink** (Resolve's Fusion scan doesn't reliably follow symlinks) — it's a real file that `exec()`s the repo source

## Known gotchas

1. **Resolve Free has no Fusion UIManager.** The `fusion` global exists but `fusion.UIManager` is `None`. That's why the UI is now web-based instead of Fusion native. Don't bring back Fusion UI without Studio.
2. **`timeline.AddMarker(frameId, ...)` takes an offset from timeline start, NOT the absolute frame number.** Passing `start_frame + offset` puts markers at 2× their intended position. See `markers.apply_markers`.
3. **`AddMarker` returns False if a marker already exists at that frame.** Expose a "Clear ALL" before adding to avoid this silently dropping markers.
4. **Whisper shells out to bare `ffmpeg`**, not to the path in Python. Must prepend ffmpeg's dir to `os.environ["PATH"]` before `model.transcribe()`.
5. **Audio duration parsing may return 0** if ffmpeg stderr format differs — the heartbeat's expected-time fallback is `max(2.0, duration/speed)`.
6. **Tkinter `.after()` from non-main threads is flaky on macOS.** The web UI avoids this entirely; if ever reverting to Tk, use a queue + main-thread polling.
7. **Sandboxed App Store Resolve (`com.blackmagic-design.DaVinciResolveLite`)** can't read scripts from `~/Library` and can't run `ffmpeg` subprocess. Tell the user to install the free version from blackmagicdesign.com directly.

## How the web UI works

- `ai_edit_assistant.main()` creates a `SharedState`, registers handlers for `analyze`/`prompt`/`clear_markers`, starts the server, opens a browser.
- Browser polls `/api/status` every ~400ms — gets `{text, pct, preview?}` and updates the status bar + progress.
- `POST /api/analyze` fires-and-forgets a worker thread that does the full pipeline. The worker writes to `state.set_status(...)` as it progresses.
- Marker preview: worker calls `state.request_preview(markers)` which blocks on a `threading.Event`. The next `/api/status` poll delivers `preview` to the frontend. Frontend shows modal, user picks, `POST /api/apply_preview {indices}` resolves the event — worker continues.
- `POST /api/prompt` synchronously runs `prompt_editor.run_prompt()`, returns `{explanation, results}` JSON.

## Provider abstraction

`analyze.llm_complete(prompt, max_tokens)` — provider-agnostic. Dispatches to Anthropic or OpenAI based on:
1. `AI_PROVIDER` env var (explicit)
2. Whichever API key is set
3. Default: Anthropic

Both `analyze_transcript` and `generate_chapters` use it. If you add new LLM calls, use the same helper.

## Diagnostic files

When stuff breaks, these logs are ground truth (not stdout — which is swallowed by Resolve):
- `~/.resolve-ai-assistant/whisper.log` — transcribe pipeline + marker application
- `~/.resolve-ai-assistant/prompt.log` — prompt mode

Pipe-to-log pattern used throughout: `with open(log_path, "a") as f: f.write(...)`.

## Commit hygiene

- The Tk UI in `tk_ui.py` is intentionally dead code. Don't delete until the web UI is proven in production; it's useful if the web approach ever has to be abandoned.
- `fusion` and `resolve` scripting objects are PyRemoteObjects — don't try to pickle or deepcopy them.
- Never commit `.env` or anything under `~/.resolve-ai-assistant/`.

## Useful commands

Quick compile-check all sources:
```bash
cd src && python3 -m py_compile *.py && echo OK
```

Test the CLI standalone:
```bash
python src/cli.py analyze -v short_clip.mp4 -o /tmp/markers.json --fillers --chapters
```

Test the web UI without Resolve (fake Resolve object → server only):
Not currently wired up. Would be a nice addition.

Reinstall launcher after editing `install.sh`:
```bash
./install.sh
```

## Open tasks (from user conversations)

- Upgrade prompt mode from single-shot to iterative tool-use (OpenAI function calling / Anthropic tools)
- Add a "Stop" button in the web UI to cleanly shut down the server
- Speaker diarization (whisperX / pyannote) + per-speaker marker coloring
- B-roll suggestion markers
- Thumbnail frame picker at highlight markers
- Local-only mode (Ollama + whisper.cpp)
- Per-creator style profile feeding into analysis prompts
- Clean up diagnostic `log()` spam from `markers.py` and `transcribe.py` once stable
