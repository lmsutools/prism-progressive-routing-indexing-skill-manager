#!/usr/bin/env python3
"""
PRISM Layer 2: Forensic Skill Auditor & Bundle Validator (audit_skills.py)

Combines the best engineering gates from:
- obra/superpowers:
  * SDO/CSO Frontmatter check: `description` starts with "Use when...", < 350 chars
    recommended (< 500 warning, < 1024 hard cap), no workflow summary shortcuts.
  * 20,000-byte Compaction Cliff check (Claude Code / harness compaction cut).
  * Zero `@path` force-load syntax check.
- rebelytics/one-skill-to-rule-them-all:
  * Core-Size Ratchet (`.core-ceiling` or `core_max_lines` frontmatter) with
    one-way downward enforcement (CEILING_SLACK_TOLERANCE = 3 lines).
  * Reference file line ceilings (`references/ceilings.txt`).
  * Static path verification for all cited `references/*`, `scripts/*`, `assets/*`,
    and `resources/*` files.
  * Edit residue detection (merge conflict markers, unresolved `{{SLOTS}}`, regex `\\1`).
- hussi9/skill-router:
  * TF-IDF trigger keyword extraction & pairwise Semantic Trigger Collision detection.
  * Startup Token Tax calculation across Global Active vs. Cold Vault vs. Built-in.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# --- Thresholds & Constants --------------------------------------------------
COMPACTION_BYTE_LIMIT = 20_000          # obra/superpowers compaction truncation cliff
SUBAGENT_FIREWALL_BYTES = 8_000         # PRISM Layer 4 threshold for Subagent Isolation
DESC_OPTIMAL_CHARS = 350                # PRISM SDO target description length
DESC_WARN_CHARS = 500                   # obra/superpowers recommended max
DESC_HARD_MAX_CHARS = 1024              # agentskills.io specification hard cap
CEILING_SLACK_TOLERANCE = 3             # rebelytics ratchet slack tolerance
COLLISION_SIMILARITY_THRESHOLD = 0.32   # Jaccard/Cosine overlap warning threshold

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
AT_FORCE_LOAD_RE = re.compile(r"(?<![a-zA-Z0-9._%+-])@(?:skills|references|scripts|resources)/[^\s)`]+")

# Workflow-summary phrases in description that tempt agents to skip reading SKILL.md
WORKFLOW_SHORTCUT_PATTERNS = [
    (re.compile(r"\b(step\s*1|first\s+it|then\s+it|finally\s+it|dispatches\s+subagent\s+per)\b", re.I),
     "summarizes step-by-step workflow in description (triggers SDO shortcut bug)"),
    (re.compile(r"^(?:a\s+|an\s+|the\s+)?(?:comprehensive|senior-level|complete|ultimate|all-in-one)\s+(?:guide|playbook|skill|toolkit|framework)\b", re.I),
     "starts with a capability pitch instead of 'Use when...' trigger conditions"),
]

# Edit residue patterns (from rebelytics/one-skill-to-rule-them-all)
RESIDUE_PATTERNS = [
    (re.compile(r"(?m)^\\[0-9]\s*$"), "literal regex backreference on its own line"),
    (re.compile(r"(?m)^(<<<<<<<|=======|>>>>>>>)( |$)"), "git merge conflict marker"),
    (re.compile(r"\{\{[A-Za-z_][A-Za-z0-9_ .-]*\}\}"), "unresolved template slot {{...}}"),
    (re.compile(r"\b(TODO|FIXME|XXX)\b:\s*(fill|replace|write)", re.I), "unfinished placeholder note"),
]

# Cited relative paths inside SKILL.md (backticks and markdown links)
MD_LINK_RE = re.compile(r"\]\(((?:\./)?(?:references|scripts|resources|assets|examples)/[^)#\s\]]+)")
BACKTICK_PATH_RE = re.compile(r"`((?:\./)?(?:references|scripts|resources|assets|examples)/[^`\s*?]+\.[A-Za-z0-9]+)`")
CMD_PATH_RE = re.compile(r"(?<![\[/A-Za-z0-9_.-])(?:references|scripts|resources|assets|examples)/[^\s`'\"*?<>;|&)\[\]]+\.[A-Za-z0-9]+")

STOPWORDS = frozenset("""
a an the and or but if then else for to of in on at by with from into onto over under
is are was were be been being do does did doing have has had having can could should
would will shall may might must this that these those it its you your we our us me my
use used using when whenever where how what which who why all any both each more most
other some such no nor not only own same so than too very just now also about after
before duringskill skills agent agents user asks wants task tasks workflow workflows
file files code project projects guide playbook comprehensive senior level
""".split())

WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in WORD_RE.findall(text.lower()):
        parts = [raw] + raw.replace("_", "-").split("-") if ("-" in raw or "_" in raw) else [raw]
        for p in parts:
            p = p.strip(".")
            if len(p) >= 3 and p not in STOPWORDS and not p.isdigit():
                tokens.append(p)
    return tokens


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter keys (supporting > and | block scalars) and body."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), m.group(2)
    fm: dict[str, str] = {}

    # Parse simple key-values and multiline block scalars
    lines = fm_raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            if val in (">", ">-", "|", "|-", ">+", "|+"):
                block_lines: list[str] = []
                i += 1
                while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t") or not lines[i].strip()):
                    block_lines.append(lines[i].strip())
                    i += 1
                joiner = " " if val.startswith(">") else "\n"
                fm[key] = joiner.join(b for b in block_lines if b).strip()
                continue
            elif not val:
                # Continuation lines indented on next lines
                block_lines = []
                i += 1
                while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                    block_lines.append(lines[i].strip())
                    i += 1
                fm[key] = " ".join(block_lines).strip()
                continue
            else:
                fm[key] = val.strip("\"'")
        i += 1
    return fm, body


def discover_skill_roots(include_builtin: bool = False) -> list[tuple[str, str, Path]]:
    """Return (tier_label, harness_name, path) for all known skill locations."""
    home = Path.home()
    roots: list[tuple[str, str, Path]] = [
        ("tier0_global", "antigravity", home / ".gemini" / "config" / "skills"),
        ("tier0_global", "antigravity-legacy", home / ".gemini" / "antigravity" / "skills"),
        ("tier0_global", "claude", home / ".claude" / "skills"),
        ("tier0_global", "codex", home / ".codex" / "skills"),
        ("tier0_global", "agents-shared", home / ".agents" / "skills"),
        ("tier2_vault", "prism-vault", home / ".agents" / "vault"),
    ]
    cwd = Path.cwd()
    for ws_dir in (".agents/skills", ".agent/skills", ".claude/skills", ".codex/skills"):
        candidate = cwd / ws_dir
        if candidate.exists():
            roots.append(("tier1_workspace", "workspace", candidate))

    if include_builtin:
        roots.append(("builtin", "antigravity-builtin", home / ".gemini" / "antigravity" / "builtin" / "skills"))

    return [(tier, harness, p) for tier, harness, p in roots if p.exists() and p.is_dir()]


def extract_cited_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for m in MD_LINK_RE.finditer(text):
        paths.add(m.group(1).lstrip("./"))
    for m in BACKTICK_PATH_RE.finditer(text):
        paths.add(m.group(1).lstrip("./"))
    for m in CMD_PATH_RE.finditer(text):
        paths.add(m.group(0).lstrip("./"))
    # Exclude placeholder paths containing <...> or {...}
    return {p for p in paths if "<" not in p and "{" not in p and not p.endswith(".")}


def audit_single_skill(skill_dir: Path, tier: str, harness: str) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    raw_bytes = skill_md.read_bytes()
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    line_count = len(lines)
    byte_count = len(raw_bytes)

    fm, body = parse_frontmatter(text)
    name = fm.get("name", skill_dir.name)
    desc = fm.get("description", "")
    desc_chars = len(desc)
    desc_words = len(desc.split())
    # Approx 1.33 tokens per word + YAML wrapper
    startup_tokens = int(round((desc_words + len(name.split("-"))) * 1.35)) + 8 if tier in ("tier0_global", "tier1_workspace", "builtin") else 0
    body_tokens = int(round(len(text.split()) * 1.35))

    errors: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    # 1. Frontmatter presence & Name format
    if not fm:
        errors.append("Missing YAML frontmatter (`---` block at top of SKILL.md)")
    if not name:
        errors.append("Missing `name:` in YAML frontmatter")
    elif not NAME_RE.match(name) and tier != "builtin":
        warnings.append(f"Skill name `{name}` should be lowercase kebab-case (`[a-z0-9-]+`)")

    # 2. SDO / CSO Description checks (obra/superpowers rules)
    if not desc:
        errors.append("Missing `description:` in YAML frontmatter")
    else:
        if desc_chars > DESC_HARD_MAX_CHARS:
            errors.append(f"Description is {desc_chars} chars (exceeds {DESC_HARD_MAX_CHARS} hard specification cap)")
        elif desc_chars > DESC_WARN_CHARS:
            warnings.append(f"Description bloat: {desc_chars} chars / {desc_words} words (obra SDO limit is <{DESC_WARN_CHARS} chars, PRISM target <{DESC_OPTIMAL_CHARS})")
        elif desc_chars > DESC_OPTIMAL_CHARS:
            suggestions.append(f"Description is {desc_chars} chars (trimming under {DESC_OPTIMAL_CHARS} chars saves startup context)")

        if not re.match(r"^(?:use|invoke|activate|trigger)\s+(?:this\s+skill\s+)?(?:when|whenever|for|to|if)\b", desc.strip(), re.I):
            warnings.append("SDO violation: Description does not start with 'Use when...' (leads with summary instead of trigger conditions)")

        for pat, reason in WORKFLOW_SHORTCUT_PATTERNS:
            if pat.search(desc):
                warnings.append(f"SDO shortcut risk: {reason}")
                break

    # 3. Compaction Cliff & Subagent Firewall weight
    if byte_count >= COMPACTION_BYTE_LIMIT:
        errors.append(f"SKILL.md is {byte_count:,} bytes — exceeds {COMPACTION_BYTE_LIMIT:,}B compaction truncation cliff! Move sections to `references/`.")
    elif byte_count >= 15_000:
        warnings.append(f"SKILL.md is {byte_count:,} bytes (approaching {COMPACTION_BYTE_LIMIT:,}B compaction cliff)")

    # 4. `@` Force-load syntax check
    at_matches = AT_FORCE_LOAD_RE.findall(text)
    if at_matches:
        errors.append(f"Contains `@` force-load paths ({', '.join(at_matches[:3])}) which burn context immediately. Use standard Markdown links.")

    # 5. Core-Size Ratchet check (rebelytics rule)
    ceiling_file = skill_dir / ".core-ceiling"
    declared_ceiling: int | None = None
    if "core_max_lines" in fm and fm["core_max_lines"].isdigit():
        declared_ceiling = int(fm["core_max_lines"])
    elif ceiling_file.is_file():
        try:
            declared_ceiling = int(ceiling_file.read_text(encoding="utf-8").strip().splitlines()[0])
        except ValueError:
            errors.append("Invalid integer in `.core-ceiling`")

    if declared_ceiling is not None:
        if line_count > declared_ceiling:
            errors.append(f"Core-size ratchet failed: SKILL.md is {line_count} lines (exceeds ceiling of {declared_ceiling} lines)")
        elif declared_ceiling - line_count > CEILING_SLACK_TOLERANCE:
            warnings.append(
                f"Core-size ratchet slack: SKILL.md is {line_count} lines but ceiling is {declared_ceiling}. "
                f"Lower ceiling to {line_count} to lock in savings!"
            )
    else:
        suggestions.append(f"No `.core-ceiling` or `core_max_lines` ratchet set (current: {line_count} lines)")

    # 6. Reference ceilings check (`references/ceilings.txt`)
    ceilings_txt = skill_dir / "references" / "ceilings.txt"
    if ceilings_txt.is_file():
        for raw_line in ceilings_txt.read_text(encoding="utf-8").splitlines():
            s = raw_line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) >= 2 and parts[1].isdigit():
                ref_name, ref_cap = parts[0], int(parts[1])
                ref_path = skill_dir / "references" / ref_name
                if not ref_path.is_file():
                    errors.append(f"`references/ceilings.txt` lists missing file `references/{ref_name}`")
                else:
                    ref_lines = len(ref_path.read_text(encoding="utf-8", errors="replace").splitlines())
                    if ref_lines > ref_cap:
                        errors.append(f"`references/{ref_name}` is {ref_lines} lines (exceeds ceiling {ref_cap})")
                    elif ref_cap - ref_lines > CEILING_SLACK_TOLERANCE:
                        warnings.append(f"`references/{ref_name}` ceiling ({ref_cap}) has slack above actual lines ({ref_lines})")

    # 7. Cited relative paths existence check
    cited_paths = extract_cited_paths(body)
    missing_paths = [rel for rel in sorted(cited_paths) if not (skill_dir / rel).exists()]
    if missing_paths:
        errors.append(f"Broken relative paths cited in SKILL.md: {', '.join(missing_paths[:5])}")

    # 8. Edit residue check
    if "<!-- template: slots intentional -->" not in text:
        for pat, why in RESIDUE_PATTERNS:
            if pat.search(text):
                errors.append(f"Edit residue detected in SKILL.md: {why}")

    # 9. Compute health score (0-100)
    score = 100
    score -= len(errors) * 25
    score -= len(warnings) * 10
    score -= len(suggestions) * 2
    score = max(0, score)

    # Calculate reference footprint (lazy-loaded bytes)
    ref_bytes = 0
    ref_files = 0
    for sub in ("references", "scripts", "resources", "examples", "assets"):
        sub_dir = skill_dir / sub
        if sub_dir.is_dir():
            for f in sub_dir.rglob("*"):
                if f.is_file() and not f.name.startswith(".") and "__pycache__" not in f.parts:
                    ref_bytes += f.stat().st_size
                    ref_files += 1

    return {
        "name": name,
        "dir_name": skill_dir.name,
        "path": str(skill_dir),
        "is_symlink": skill_dir.is_symlink(),
        "tier": tier,
        "harness": harness,
        "line_count": line_count,
        "byte_count": byte_count,
        "ref_files": ref_files,
        "ref_bytes": ref_bytes,
        "desc_chars": desc_chars,
        "desc_words": desc_words,
        "startup_tokens": startup_tokens,
        "body_tokens": body_tokens,
        "execution_mode": "SUBAGENT_FIREWALL" if (byte_count + ref_bytes) >= SUBAGENT_FIREWALL_BYTES else "INLINE",
        "declared_ceiling": declared_ceiling,
        "description": desc,
        "keywords": tokenize(f"{name} {desc}"),
        "errors": errors,
        "warnings": warnings,
        "suggestions": suggestions,
        "score": score,
    }


def detect_collisions(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect pairs of active skills with high trigger-word overlap."""
    collisions: list[dict[str, Any]] = []
    active = [s for s in skills if s["tier"] != "tier2_vault"]
    unique_by_name: dict[str, dict[str, Any]] = {}
    for s in active:
        unique_by_name.setdefault(s["name"], s)
    items = list(unique_by_name.values())

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            # Compare top 18 trigger tokens from each skill
            set_a = set(a["keywords"][:18])
            set_b = set(b["keywords"][:18])
            if not set_a or not set_b:
                continue
            shared = sorted(set_a & set_b)
            min_len = min(len(set_a), len(set_b))
            overlap = len(shared) / min_len if min_len else 0.0
            if overlap >= COLLISION_SIMILARITY_THRESHOLD and len(shared) >= 4:
                collisions.append({
                    "skill_a": a["name"],
                    "skill_b": b["name"],
                    "similarity": round(overlap, 2),
                    "shared_triggers": shared[:8],
                })
    return sorted(collisions, key=lambda c: c["similarity"], reverse=True)


def generate_sdo_suggestion(skill: dict[str, Any]) -> str | None:
    """Propose an SDO-compliant rewrite template if a skill's description has warnings."""
    desc = skill["description"]
    if not desc:
        return None
    # Check if there is a "Use this skill when" or "Activate this skill when" sentence inside
    m = re.search(r"((?:Use|Activate)\s+(?:this\s+skill\s+)?when\b.+)$", desc, re.I | re.S)
    if m:
        candidate = m.group(1).strip()
        candidate = re.sub(r"^(?:Use|Activate)\s+this\s+skill\s+when\b", "Use when", candidate, flags=re.I)
        if len(candidate) < len(desc):
            return candidate
    return None


def run_audit(target_dir: Path | None = None, include_builtin: bool = False) -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    seen_realpaths: set[tuple[str, Path]] = set()

    if target_dir:
        if (target_dir / "SKILL.md").is_file():
            skills.append(audit_single_skill(target_dir, "direct", "custom"))
        else:
            for child in sorted(target_dir.iterdir()):
                if child.is_dir() and (child / "SKILL.md").is_file():
                    skills.append(audit_single_skill(child, "direct", "custom"))
    else:
        for tier, harness, root in discover_skill_roots(include_builtin=include_builtin):
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "SKILL.md").is_file():
                    key = (harness, child.resolve())
                    if key in seen_realpaths:
                        continue
                    seen_realpaths.add(key)
                    skills.append(audit_single_skill(child, tier, harness))

    collisions = detect_collisions(skills)
    total_startup_tokens = sum(s["startup_tokens"] for s in skills if s["tier"] in ("tier0_global", "tier1_workspace"))
    builtin_startup_tokens = sum(s["startup_tokens"] for s in skills if s["tier"] == "builtin")
    vault_saved_tokens = sum(
        int(round((s["desc_words"] + len(s["name"].split("-"))) * 1.35)) + 8
        for s in skills if s["tier"] == "tier2_vault"
    )

    return {
        "skills": skills,
        "collisions": collisions,
        "summary": {
            "total_skills_scanned": len(skills),
            "active_user_skills": sum(1 for s in skills if s["tier"] in ("tier0_global", "tier1_workspace")),
            "vaulted_skills": sum(1 for s in skills if s["tier"] == "tier2_vault"),
            "builtin_skills": sum(1 for s in skills if s["tier"] == "builtin"),
            "user_startup_tokens": total_startup_tokens,
            "builtin_startup_tokens": builtin_startup_tokens,
            "vault_saved_tokens": vault_saved_tokens,
            "total_errors": sum(len(s["errors"]) for s in skills),
            "total_warnings": sum(len(s["warnings"]) for s in skills),
            "average_score": round(sum(s["score"] for s in skills) / len(skills), 1) if skills else 100.0,
        },
    }


def print_report(report: dict[str, Any]) -> None:
    s = report["summary"]
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║  PRISM Forensic Skill Audit (SDO + Compaction + Ratchet + Collisions)   ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print(
        f"  Skills Scanned: {s['total_skills_scanned']} "
        f"(Active User: {s['active_user_skills']} | Vaulted: {s['vaulted_skills']} | Built-in: {s['builtin_skills']})"
    )
    print(
        f"  Startup Token Tax (per chat): {s['user_startup_tokens']} user tokens "
        f"(+ {s['builtin_startup_tokens']} built-in) | Vault Savings: {s['vault_saved_tokens']} tokens"
    )
    print(
        f"  Health Score: {s['average_score']}/100 "
        f"({s['total_errors']} errors, {s['total_warnings']} warnings)\n"
    )

    print(f"{'SKILL NAME':<26} {'HARNESS/TIER':<20} {'CORE':<8} {'REFS':<9} {'DESC':<8} {'TAX':<7} {'SCORE'}")
    print("─" * 90)
    for sk in report["skills"]:
        tier_short = f"{sk['harness']}"
        core_kb = f"{sk['byte_count']/1024:.1f}KB"
        ref_kb = f"{sk['ref_bytes']/1024:.1f}KB"
        desc_c = f"{sk['desc_chars']}c"
        tax = f"{sk['startup_tokens']}t"
        status = "✅" if (not sk["errors"] and not sk["warnings"]) else ("❌" if sk["errors"] else "⚠️")
        print(f"{sk['name'][:25]:<26} {tier_short[:19]:<20} {core_kb:<8} {ref_kb:<9} {desc_c:<8} {tax:<7} {status} {sk['score']}")

        for err in sk["errors"]:
            print(f"   ❌ ERROR: {err}")
        for warn in sk["warnings"]:
            print(f"   ⚠️  WARN:  {warn}")
        sdo_fix = generate_sdo_suggestion(sk)
        if sdo_fix and sk["warnings"]:
            print(f"   💡 SDO REWRITE ({len(sdo_fix)}c vs {sk['desc_chars']}c): \"{sdo_fix[:110]}...\"")

    if report["collisions"]:
        print("\n⚡ Semantic Trigger Collisions Detected:")
        for col in report["collisions"]:
            print(
                f"  • {col['skill_a']} ↔ {col['skill_b']} "
                f"(overlap: {int(col['similarity']*100)}%) — shared: {', '.join(col['shared_triggers'])}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRISM Forensic Skill Auditor & Validator")
    parser.add_argument("path", nargs="?", help="Optional specific skill directory or parent folder to audit")
    parser.add_argument("--include-builtin", action="store_true", help="Also audit built-in platform skills")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any errors or warnings exist")
    parser.add_argument("--lock-ratchet", action="store_true", help="Write/update .core-ceiling for the target skill")
    args = parser.parse_args(argv)

    target = Path(args.path).resolve() if args.path else None
    if args.lock_ratchet and target and (target / "SKILL.md").is_file():
        lines = len((target / "SKILL.md").read_text(encoding="utf-8").splitlines())
        (target / ".core-ceiling").write_text(f"{lines}\n", encoding="utf-8")
        print(f"Locked .core-ceiling to {lines} lines for {target.name}")

    report = run_audit(target_dir=target, include_builtin=args.include_builtin)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    if report["summary"]["total_errors"] > 0:
        return 1
    if args.strict and report["summary"]["total_warnings"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
