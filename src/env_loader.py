#!/usr/bin/env python3
"""Tiny zero-dependency .env loader.

Scans three locations in order and applies the FIRST .env found per key.
Existing OS environment variables are NEVER overridden.

Search order:
1. ~/.resolve-ai-assistant/.env   (recommended for Resolve, persistent)
2. <repo root>/.env               (next to src/)
3. ./.env                         (current working dir)

Format: KEY=VALUE per line.
- Lines starting with # are ignored
- Blank lines ignored
- Surrounding single or double quotes on the value are stripped
- Inline comments after `#` are stripped from unquoted values
- `export KEY=VALUE` is also accepted
"""

import os
from pathlib import Path


def _parse_env_file(path: Path) -> dict:
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if not key:
                    continue
                # Strip matching surrounding quotes
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                else:
                    # strip inline comment for unquoted values
                    hash_idx = val.find(" #")
                    if hash_idx != -1:
                        val = val[:hash_idx].rstrip()
                out[key] = val
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[env_loader] Could not parse {path}: {e}")
    return out


def load_env(verbose: bool = False) -> dict:
    """Load .env files into os.environ. Returns the effective overrides applied."""
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        Path.home() / ".resolve-ai-assistant" / ".env",
        repo_root / ".env",
        Path.cwd() / ".env",
    ]

    applied = {}
    for path in candidates:
        if not path.exists():
            continue
        parsed = _parse_env_file(path)
        for k, v in parsed.items():
            if k in os.environ:
                continue  # never override real env vars
            if k in applied:
                continue  # earlier file wins
            os.environ[k] = v
            applied[k] = v
        if verbose:
            print(f"[env_loader] Loaded {len(parsed)} keys from {path}")

    return applied


if __name__ == "__main__":
    loaded = load_env(verbose=True)
    print(f"Applied {len(loaded)} keys.")
    for k in loaded:
        print(f"  {k} = ***")
