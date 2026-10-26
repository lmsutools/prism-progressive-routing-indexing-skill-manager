#!/usr/bin/env python3
"""
PRISM Layer 3 & 4: Dual-Leg Triage Router & Subagent Firewall (route_task.py)

Combines the best mechanics of:
- hussi9/skill-router:
  * Weighted ranking (`name`: 3.0, `use_when`: 2.5, `keywords`: 1.5, `description`: 1.0).
  * Evidence gate (ignores generic chatter & short conversational inputs).
  * Dual-Leg Chain: pairs Leg 1 (Domain Skill) + Leg 2 (Process Skill).
  * Subagent Dispatch Brief: generates a ready-to-send prompt block for `invoke_subagent`
    when a skill exceeds the Subagent Firewall weight (>= 8KB) or runs a deep audit.
- pcx-wave/skill-router:
  * Fast-exit gate on conversational prompts (< 6 words or simple questions).
- Antigravity & Claude Code Hook Compatibility:
  * `--hook antigravity`: emits `PreInvocation` JSON (`{"injectSteps": [{"ephemeralMessage": "..."}]}`)
  * `--hook claude`: emits `UserPromptSubmit` JSON (`{"systemMessage": "...", "hookSpecificOutput": ...}`)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from audit_skills import tokenize  # noqa: E402
from build_index import INDEX_JSON_PATH, build_and_save  # noqa: E402

SYNONYMS: dict[str, list[str]] = {
    "rust": ["cargo", "crate", "rustc", "tokio", "borrow", "clippy"],
    "cargo": ["rust", "crate", "compile", "linker"],
    "slow": ["compile", "latency", "performance", "speed", "timings"],
    "schedule": ["cron", "timer", "recurring", "automation"],
    "chart": ["diagram", "widget", "visual", "html", "generative_ui"],
    "ui": ["widget", "interactive", "panel", "plugin", "generative_ui"],
    "bloat": ["prism", "tokens", "context", "description", "router", "vault"],
    "skill": ["prism", "custom", "agy", "plugin", "workflow"],
}

GENERIC_WEAK_TOKENS = frozenset({
    "app", "build", "create", "project", "work", "fast", "good", "best",
    "check", "system", "setup", "write", "read", "test", "problem", "issue",
})


def load_index() -> list[dict[str, Any]]:
    if not INDEX_JSON_PATH.is_file():
        build_and_save(include_builtin=True)
    try:
        data = json.loads(INDEX_JSON_PATH.read_text(encoding="utf-8"))
        return data.get("entries", [])
    except Exception:
        build_and_save(include_builtin=True)
        data = json.loads(INDEX_JSON_PATH.read_text(encoding="utf-8"))
        return data.get("entries", [])


def expand_query_tokens(tokens: list[str]) -> tuple[set[str], set[str]]:
    direct = set(tokens)
    expanded: set[str] = set()
    for t in direct:
        for syn in SYNONYMS.get(t, []):
            if syn not in direct:
                expanded.add(syn)
    return direct, expanded


def score_entry(entry: dict[str, Any], direct: set[str], expanded: set[str], raw_prompt: str) -> tuple[float, list[str]]:
    name_tokens = set(tokenize(entry["name"]))
    use_when_tokens = set(tokenize(" ".join(entry.get("use_when", []))))
    kw_tokens = set(entry.get("keywords", []))
    desc_tokens = set(tokenize(entry.get("description", "")))

    score = 0.0
    matched_evidence: list[str] = []

    # 1. Exact skill name mention in prompt
    if entry["name"].lower() in raw_prompt.lower():
        score += 12.0
        matched_evidence.append(f"name:{entry['name']}")

    # 2. Field-weighted direct matches (hussi9 weights: name 3.0, use_when 2.5, keywords 1.5, desc 1.0)
    for tok in direct:
        weight = 1.0 if tok not in GENERIC_WEAK_TOKENS else 0.25
        hit = False
        if tok in name_tokens:
            score += 3.0 * weight
            hit = True
        if tok in use_when_tokens:
            score += 2.5 * weight
            hit = True
        if tok in kw_tokens:
            score += 1.5 * weight
            hit = True
        elif tok in desc_tokens:
            score += 1.0 * weight
            hit = True
        if hit and tok not in GENERIC_WEAK_TOKENS:
            matched_evidence.append(tok)

    # 3. Half credit for synonym matches
    for syn in expanded:
        if syn in name_tokens or syn in kw_tokens or syn in use_when_tokens:
            score += 1.25
            matched_evidence.append(f"~{syn}")

    # 4. Priority boost for user/vault skills over generic built-ins
    if score > 0 and entry.get("tier") in ("tier0_global", "tier1_workspace", "tier2_vault"):
        score *= 1.15

    # Evidence gate: require at least 1 non-generic evidence token or score >= 5.0
    distinct_hits = [m for m in matched_evidence if not m.startswith("~")]
    if not distinct_hits and score < 5.0:
        return 0.0, []

    return round(score, 2), matched_evidence[:6]


def route_prompt(prompt: str, min_score: float = 4.0) -> dict[str, Any]:
    words = prompt.strip().split()
    if len(words) < 4 and not prompt.strip().startswith("/"):
        return {"routed": False, "reason": "short_conversational_prompt"}

    entries = load_index()
    q_tokens = tokenize(prompt)
    if not q_tokens:
        return {"routed": False, "reason": "no_distinctive_tokens"}

    direct, expanded = expand_query_tokens(q_tokens)

    domain_candidates: list[dict[str, Any]] = []
    process_candidates: list[dict[str, Any]] = []

    for e in entries:
        sc, ev = score_entry(e, direct, expanded, prompt)
        if sc >= min_score:
            item = {
                "name": e["name"],
                "kind": e["kind"],
                "tier": e["tier"],
                "path": e["path"],
                "execution_mode": e["execution_mode"],
                "core_bytes": e["core_bytes"],
                "ref_bytes": e["ref_bytes"],
                "score": sc,
                "evidence": ev,
            }
            if e["kind"] == "process":
                process_candidates.append(item)
            else:
                domain_candidates.append(item)

    domain_candidates.sort(key=lambda x: x["score"], reverse=True)
    process_candidates.sort(key=lambda x: x["score"], reverse=True)

    primary = domain_candidates[0] if domain_candidates else (process_candidates[0] if process_candidates else None)
    if not primary:
        return {"routed": False, "reason": "below_confidence_threshold"}

    secondary_process = process_candidates[0] if (domain_candidates and process_candidates) else None
    runner_up = domain_candidates[1] if len(domain_candidates) > 1 else None

    # Build Subagent Firewall Brief if primary is heavy (>= 8KB total package)
    subagent_brief = None
    if primary["execution_mode"] == "SUBAGENT_FIREWALL":
        subagent_brief = (
            f"Read and follow `{primary['path']}` to execute this task. "
            f"Only load files inside its `references/` folder that match the specific workflow step. "
            f"Return a concise summary of actions, findings, and verification results."
        )

    return {
        "routed": True,
        "primary": primary,
        "process_leg": secondary_process,
        "runner_up": runner_up,
        "subagent_brief": subagent_brief,
    }


def format_route_card(result: dict[str, Any]) -> str:
    if not result.get("routed"):
        return ""
    p = result["primary"]
    proc = result.get("process_leg")
    lines = [
        f"[PRISM Route Card] Matched `{p['name']}` (score={p['score']}, tier={p['tier']}, evidence={','.join(p['evidence'])})",
        f"▶ Domain/Primary Skill: `{p['name']}` → Read `{p['path']}`",
    ]
    if proc:
        lines.append(f"▶ Process Leg: `{proc['name']}` → Read `{proc['path']}`")
    if p["execution_mode"] == "SUBAGENT_FIREWALL":
        total_kb = (p["core_bytes"] + p["ref_bytes"]) / 1024.0
        lines.append(
            f"🛡️ Subagent Firewall Recommended ({total_kb:.1f}KB total package): "
            f"For deep audits or multi-step execution, delegate via `invoke_subagent` with brief: "
            f"\"{result['subagent_brief']}\""
        )
    else:
        lines.append("⚡ Execution Mode: INLINE (lightweight skill — read `SKILL.md` directly in main thread).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRISM Dual-Leg Router & Subagent Brief Generator")
    parser.add_argument("prompt", nargs="?", help="User prompt to route (or pass via stdin)")
    parser.add_argument("--hook", choices=["antigravity", "claude"], help="Emit hook-compatible JSON payload")
    parser.add_argument("--json", action="store_true", help="Emit raw routing JSON")
    args = parser.parse_args(argv)

    raw_input = args.prompt
    if not raw_input and not sys.stdin.isatty():
        stdin_text = sys.stdin.read().strip()
        # Check if stdin is a JSON hook payload
        if stdin_text.startswith("{"):
            try:
                payload = json.loads(stdin_text)
                raw_input = (
                    payload.get("prompt")
                    or payload.get("userPrompt")
                    or payload.get("query")
                    or ""
                )
            except json.JSONDecodeError:
                raw_input = stdin_text
        else:
            raw_input = stdin_text

    if not raw_input:
        if args.hook:
            print("{}")
            return 0
        print("Usage: route_task.py \"<user prompt>\"", file=sys.stderr)
        return 0

    result = route_prompt(raw_input)
    card = format_route_card(result)

    if args.hook == "antigravity":
        if not card:
            print("{}")
        else:
            print(json.dumps({
                "injectSteps": [
                    {"ephemeralMessage": card}
                ]
            }))
        return 0

    if args.hook == "claude":
        if not card:
            print("{}")
        else:
            print(json.dumps({
                "systemMessage": card,
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": card,
                },
            }))
        return 0

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    if card:
        print(card)
    else:
        print(f"[PRISM] No skill routed ({result.get('reason', 'none')}) — answer directly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
