#!/usr/bin/env python3
"""
PRISM Layer 1 & 3: Shadow Indexer & Hub Table Generator (build_index.py)

Inspired by hussi9/skill-router (`build_index.py`) and pcx-wave/skill-router:
1. Scans Active Global skills, Workspace skills, and the Cold Vault (`~/.agents/vault`).
2. Builds `~/.agents/prism_index.json` with SHA1 content hashing, extracted `use_when`
   clauses, TF-IDF distinctive keywords, `kind` classification (`domain`, `process`,
   `design`, `meta`), and Subagent Firewall weight (`INLINE` vs `SUBAGENT_FIREWALL`).
3. Generates a compact (<1,000 token) Hub-and-Spoke markdown index (`references/_INDEX.md`)
   so any agent in any harness (Antigravity, Claude Code, Codex) can route to Cold Vault
   skills at zero idle startup cost.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from audit_skills import (  # noqa: E402
    SUBAGENT_FIREWALL_BYTES,
    discover_skill_roots,
    parse_frontmatter,
    tokenize,
)

INDEX_JSON_PATH = Path.home() / ".agents" / "prism_index.json"
DEFAULT_HUB_MD_PATH = HERE.parent / "references" / "_INDEX.md"

PROCESS_NAMES = frozenset({
    "test-driven-development", "systematic-debugging", "writing-plans",
    "executing-plans", "verification-before-completion", "subagent-driven-development",
    "requesting-code-review", "receiving-code-review", "brainstorming",
    "refactor", "code-review", "security-review", "debug", "tdd",
})
META_NAMES = frozenset({
    "prism", "skill-router", "skill-creator", "writing-skills", "using-superpowers",
    "task-observer", "agy-customizations", "antigravity-guide", "migrate-workflows", "plugin",
})
DESIGN_RE = re.compile(
    r"\b(design|ui|ux|frontend|css|tailwind|canvas|generative_ui|widget|visual|diagram)\b",
    re.I,
)
USE_WHEN_RE = re.compile(
    r"(?:^|[.;\n])\s*((?:use|invoke|activate|trigger)\s+(?:this\s+skill\s+)?"
    r"(?:when|whenever|for|to|if)\b[^.;\n]{8,180})",
    re.I,
)
WHEN_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:when to use|use when|choose the workflow|triggers?)\b.*$",
    re.I | re.M,
)
BULLET_RE = re.compile(r"^\s*(?:[-*]|\|)\s+(.{6,140})$", re.M)


def classify_kind(name: str, desc: str) -> str:
    base = name.split(":")[-1].lower()
    if base in META_NAMES:
        return "meta"
    if base in PROCESS_NAMES or name.startswith("superpowers:"):
        return "process"
    if DESIGN_RE.search(f"{name} {desc}"):
        return "design"
    return "domain"


def extract_use_when(desc: str, body: str) -> list[str]:
    triggers: list[str] = []
    for m in USE_WHEN_RE.finditer(desc):
        cleaned = re.sub(
            r"^(?:use|invoke|activate|trigger)\s+(?:this\s+skill\s+)?(?:when|whenever|for|to|if)\s+",
            "",
            m.group(1).strip(),
            flags=re.I,
        )
        # Split on comma-separated clauses
        for part in re.split(r",\s*(?:or\s+)?|\s+or\s+", cleaned):
            part = part.strip(" .,;:")
            if 6 <= len(part) <= 90 and part not in triggers:
                triggers.append(part)

    # Also inspect any "## When to use" or "## Choose the workflow" table/list in body
    hm = WHEN_HEADING_RE.search(body)
    if hm:
        section = body[hm.end():hm.end() + 1500]
        next_h = re.search(r"^#{1,3}\s+", section, re.M)
        if next_h:
            section = section[:next_h.start()]
        for bm in BULLET_RE.finditer(section):
            item = bm.group(1).strip()
            if "|" in item:
                cols = [c.strip() for c in item.strip("|").split("|")]
                if cols and not cols[0].startswith(":") and cols[0].lower() != "situation":
                    item = cols[0]
            item = re.sub(r"[`*_]", "", item).strip()
            if 6 <= len(item) <= 80 and item not in triggers:
                triggers.append(item)

    return triggers[:8]


def build_catalog_entries(include_builtin: bool = True) -> list[dict[str, Any]]:
    raw_entries: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Order of precedence: workspace -> global -> vault -> builtin
    roots = discover_skill_roots(include_builtin=include_builtin)
    tier_priority = {"tier1_workspace": 0, "tier0_global": 1, "tier2_vault": 2, "builtin": 3}
    roots.sort(key=lambda r: tier_priority.get(r[0], 9))

    for tier, harness, root in roots:
        for child in sorted(root.iterdir()):
            skill_md = child / "SKILL.md"
            if not (child.is_dir() and skill_md.is_file()):
                continue
            raw_bytes = skill_md.read_bytes()
            text = raw_bytes.decode("utf-8", errors="replace")
            fm, body = parse_frontmatter(text)
            name = fm.get("name", child.name)
            if name in seen_names:
                continue
            seen_names.add(name)

            desc = fm.get("description", "")
            sha1 = hashlib.sha1(raw_bytes).hexdigest()[:12]

            ref_bytes = 0
            for sub in ("references", "scripts", "resources", "examples", "assets"):
                sd = child / sub
                if sd.is_dir():
                    ref_bytes += sum(
                        f.stat().st_size for f in sd.rglob("*")
                        if f.is_file() and not f.name.startswith(".") and "__pycache__" not in f.parts
                    )

            total_weight = len(raw_bytes) + ref_bytes
            raw_entries.append({
                "name": name,
                "tier": tier,
                "harness": harness,
                "path": str(skill_md.resolve()),
                "skill_dir": str(child.resolve()),
                "source_hash": sha1,
                "kind": classify_kind(name, desc),
                "use_when": extract_use_when(desc, body),
                "description": desc,
                "core_bytes": len(raw_bytes),
                "ref_bytes": ref_bytes,
                "execution_mode": "SUBAGENT_FIREWALL" if total_weight >= SUBAGENT_FIREWALL_BYTES else "INLINE",
                "_doc_tokens": tokenize(f"{name} {name} {desc} {body[:2500]}"),
            })

    # Compute TF-IDF top keywords across the corpus
    n_docs = max(len(raw_entries), 1)
    df: Counter[str] = Counter()
    for e in raw_entries:
        for tok in set(e["_doc_tokens"]):
            df[tok] += 1

    for e in raw_entries:
        tf = Counter(e["_doc_tokens"])
        name_parts = set(e["name"].lower().split("-"))
        scored: list[tuple[float, str]] = []
        for tok, count in tf.items():
            idf = math.log(1.0 + n_docs / (1.0 + df[tok]))
            boost = 2.0 if tok in name_parts else 1.0
            scored.append((count * idf * boost, tok))
        scored.sort(reverse=True)
        e["keywords"] = [tok for _, tok in scored[:12]]
        del e["_doc_tokens"]

    return raw_entries


def write_hub_markdown(entries: list[dict[str, Any]], out_path: Path) -> str:
    """Write the compact <1,000 token Hub-and-Spoke routing table (`references/_INDEX.md`)."""
    lines = [
        "# PRISM Compact Skill Index (`_INDEX.md`)",
        "",
        "> Auto-generated by `scripts/build_index.py`. Roots: `@G`=`~/.gemini/config/skills`,",
        "> `@C`=`~/.claude/skills`, `@A`=`~/.agents/skills`, `@V`=`~/.agents/vault`, `@B`=built-in.",
        "",
        "| Skill | Kind | Mode | Top Triggers / Keywords | Location |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    home = str(Path.home())
    root_aliases = [
        (f"{home}/.gemini/config/skills/", "@G/"),
        (f"{home}/.claude/skills/", "@C/"),
        (f"{home}/.codex/skills/", "@X/"),
        (f"{home}/.agents/skills/", "@A/"),
        (f"{home}/.agents/vault/", "@V/"),
        (f"{home}/.gemini/antigravity/builtin/skills/", "@B/"),
    ]
    for e in entries:
        if e["name"] == "prism":
            continue
        triggers = ", ".join(e["keywords"][:4])
        if len(triggers) > 38:
            triggers = triggers[:35] + "..."
        mode_badge = "Sub" if e["execution_mode"] == "SUBAGENT_FIREWALL" else "Inl"
        loc = "~"
        for prefix, alias in root_aliases:
            if e["path"].startswith(prefix):
                loc = alias.rstrip("/")
                break
        lines.append(
            f"- `{e['name']}` ({loc}/{mode_badge}): {triggers}"
        )
    content = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return content


def build_and_save(include_builtin: bool = True, hub_md_path: Path = DEFAULT_HUB_MD_PATH) -> dict[str, Any]:
    entries = build_catalog_entries(include_builtin=include_builtin)
    INDEX_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0.0",
        "count": len(entries),
        "entries": entries,
    }
    INDEX_JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    hub_md = write_hub_markdown(entries, hub_md_path)
    return {
        "index_json": str(INDEX_JSON_PATH),
        "hub_md": str(hub_md_path),
        "count": len(entries),
        "hub_tokens_est": int(round(len(hub_md) / 4.0)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRISM Shadow Indexer & Hub Table Builder")
    parser.add_argument("--no-builtin", action="store_true", help="Exclude built-in skills from index")
    parser.add_argument("--hub-out", default=str(DEFAULT_HUB_MD_PATH), help="Path for _INDEX.md output")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")
    args = parser.parse_args(argv)

    res = build_and_save(include_builtin=not args.no_builtin, hub_md_path=Path(args.hub_out))
    if not args.quiet:
        print(f"✅ PRISM Index built: {res['count']} skills indexed.")
        print(f"   • Shadow JSON: {res['index_json']}")
        print(f"   • Hub Table:   {res['hub_md']} (~{res['hub_tokens_est']} tokens, budget < 1,000)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
