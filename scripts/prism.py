#!/usr/bin/env python3
"""
PRISM Unified CLI Entrypoint (prism.py)
Progressive Routing, Indexing & Skill Manager

Subcommands:
  python3 scripts/prism.py audit [--include-builtin] [--strict] [--json] [path]
  python3 scripts/prism.py index [--no-builtin]
  python3 scripts/prism.py vault <status|park|activate> [skill] [--target ...]
  python3 scripts/prism.py route "<prompt>" [--json] [--hook antigravity|claude]
  python3 scripts/prism.py hooks [--harness antigravity|claude]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import audit_skills  # noqa: E402
import build_index  # noqa: E402
import route_task  # noqa: E402
import vault_manager  # noqa: E402


def print_hooks_config(harness: str = "antigravity") -> int:
    route_script = str((HERE / "route_task.py").resolve())
    index_script = str((HERE / "build_index.py").resolve())
    if harness == "antigravity":
        cfg = {
            "prism-router": {
                "enabled": True,
                "SessionStart": [
                    {
                        "type": "command",
                        "command": f"python3 \"{index_script}\" --quiet >/dev/null 2>&1 || true",
                        "timeout": 5,
                    }
                ],
                "PreInvocation": [
                    {
                        "type": "command",
                        "command": f"python3 \"{route_script}\" --hook antigravity",
                        "timeout": 5,
                    }
                ],
            }
        }
    else:
        cfg = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup|resume",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 \"{index_script}\" --quiet >/dev/null 2>&1 || true",
                                "timeout": 5,
                            }
                        ],
                    }
                ],
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 \"{route_script}\" --hook claude",
                                "timeout": 5,
                            }
                        ]
                    }
                ],
            }
        }
    print(json.dumps(cfg, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "audit":
        return audit_skills.main(rest)
    if cmd == "index":
        return build_index.main(rest)
    if cmd == "vault":
        return vault_manager.main(rest)
    if cmd == "route":
        return route_task.main(rest)
    if cmd == "hooks":
        harness = "claude" if ("--harness" in rest and "claude" in rest) else "antigravity"
        return print_hooks_config(harness)

    print(f"Unknown subcommand: {cmd}\n\n" + __doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
