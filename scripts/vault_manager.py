#!/usr/bin/env python3
"""
PRISM Layer 1: Cold Vault & Multi-Harness Symlink Manager (vault_manager.py)

Inspired by lijianru/skills-manager (`skm`) and Hub-and-Spoke tiering:
Manages skills across 3 tiers so your startup context window stays razor-thin:
  • Tier 0 (Global Active): `~/.gemini/config/skills`, `~/.claude/skills`, `~/.codex/skills`
  • Tier 1 (Workspace Active): `<cwd>/.agents/skills` (project-specific symlinks)
  • Tier 2 (Cold Vault): `~/.agents/vault` (0 startup token cost, 100% routable via PRISM)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_index import build_and_save  # noqa: E402

VAULT_DIR = Path.home() / ".agents" / "vault"

HARNESS_TARGETS: dict[str, Path] = {
    "antigravity": Path.home() / ".gemini" / "config" / "skills",
    "claude": Path.home() / ".claude" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "shared": Path.home() / ".agents" / "skills",
}


def ensure_vault() -> Path:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    return VAULT_DIR


def find_skill_locations(skill_name: str) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for label, root in HARNESS_TARGETS.items():
        candidate = root / skill_name
        if candidate.exists() or candidate.is_symlink():
            found.append((label, candidate))
    ws_candidate = Path.cwd() / ".agents" / "skills" / skill_name
    if ws_candidate.exists() or ws_candidate.is_symlink():
        found.append(("workspace", ws_candidate))
    return found


def park_skill(skill_name: str) -> int:
    """Move a skill out of active global folders into the Cold Vault (~/.agents/vault)."""
    if skill_name == "prism":
        print("❌ Cannot vault `prism` itself — PRISM must remain in Tier 0 to route vaulted skills.", file=sys.stderr)
        return 1

    ensure_vault()
    locations = find_skill_locations(skill_name)
    vault_dest = VAULT_DIR / skill_name

    if not locations and not vault_dest.exists():
        print(f"❌ Skill `{skill_name}` not found in any active harness or vault.", file=sys.stderr)
        return 1

    # Copy/move real directory into vault first if not already there
    for _, loc in locations:
        real_path = loc.resolve()
        if not vault_dest.exists() and real_path.is_dir():
            shutil.copytree(real_path, vault_dest)
            print(f"📦 Stored canonical copy in Cold Vault: {vault_dest}")
            break

    # Remove active global/workspace entries or symlinks
    for label, loc in locations:
        if loc.is_symlink() or loc.is_file():
            loc.unlink()
        elif loc.is_dir():
            shutil.rmtree(loc)
        print(f"🧹 Removed `{skill_name}` from active {label} discovery ({loc}) → 0 startup token tax!")

    build_and_save(quiet=True) if False else build_and_save()
    return 0


def activate_skill(skill_name: str, target: str = "antigravity", workspace_dir: Path | None = None) -> int:
    """Symlink a skill from Cold Vault (or active harness) into target harness or workspace."""
    ensure_vault()
    source = VAULT_DIR / skill_name
    if not source.is_dir():
        # Check if it exists in another harness and copy/point to it
        locs = find_skill_locations(skill_name)
        if locs:
            source = locs[0][1].resolve()
        else:
            print(f"❌ Skill `{skill_name}` not found in Cold Vault ({VAULT_DIR}) or active harnesses.", file=sys.stderr)
            return 1

    if target == "workspace":
        ws_root = (workspace_dir or Path.cwd()) / ".agents" / "skills"
        ws_root.mkdir(parents=True, exist_ok=True)
        dest = ws_root / skill_name
    elif target == "all":
        for h in ("antigravity", "claude", "codex"):
            activate_skill(skill_name, target=h)
        return 0
    elif target in HARNESS_TARGETS:
        dest_root = HARNESS_TARGETS[target]
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / skill_name
    else:
        print(f"❌ Unknown target `{target}`. Choose: antigravity, claude, codex, cursor, shared, workspace, all", file=sys.stderr)
        return 1

    if dest.exists() or dest.is_symlink():
        if dest.resolve() == source.resolve():
            print(f"ℹ️  `{skill_name}` is already linked at {dest}")
            return 0
        if dest.is_symlink():
            dest.unlink()
        else:
            print(f"⚠️  Real directory already exists at {dest}; skipping overwrite.")
            return 1

    os.symlink(source, dest)
    print(f"🔗 Activated `{skill_name}` → {dest} (symlink → {source})")
    build_and_save()
    return 0


def print_status() -> int:
    ensure_vault()
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║  PRISM Layer 1: Cold Vault & Multi-Harness Skill Topology               ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")

    for label, root in list(HARNESS_TARGETS.items()) + [("workspace", Path.cwd() / ".agents" / "skills"), ("vault (Tier 2)", VAULT_DIR)]:
        if not root.exists():
            continue
        skills = [p for p in sorted(root.iterdir()) if (p.is_dir() or p.is_symlink()) and (p / "SKILL.md").is_file()]
        print(f"\n📂 {label.upper()} ({root}) — {len(skills)} skill(s):")
        if not skills:
            print("   (empty)")
        for sk in skills:
            link_info = f" -> {os.readlink(sk)}" if sk.is_symlink() else " [local dir]"
            print(f"   • {sk.name}{link_info}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRISM Cold Vault & Multi-Harness Symlink Manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show skills across Global, Workspace, and Cold Vault tiers")

    p_park = sub.add_parser("park", help="Move an active skill into the Cold Vault (~/.agents/vault) to save startup tokens")
    p_park.add_argument("skill", help="Skill directory/name to park in Cold Vault")

    p_act = sub.add_parser("activate", help="Symlink a vaulted skill into an active harness or workspace")
    p_act.add_argument("skill", help="Skill name to activate")
    p_act.add_argument("--target", default="antigravity", help="Target: antigravity, claude, codex, workspace, all")

    args = parser.parse_args(argv)
    if args.cmd == "status":
        return print_status()
    if args.cmd == "park":
        return park_skill(args.skill)
    if args.cmd == "activate":
        return activate_skill(args.skill, target=args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
