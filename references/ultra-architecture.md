# PRISM 4-Layer Ultra-Pattern Architecture

PRISM (**P**rogressive **R**outing, **I**ndexing & **S**kill **M**anager) unifies the four proven anti-bloat engineering patterns into distinct, non-conflicting layers.

---

## Layer 1: Cold Vault & Active Tiering (`vault_manager.py`)

Every skill placed in a global discovery directory (`~/.gemini/config/skills/`, `~/.claude/skills/`, `~/.codex/skills/`) injects its YAML `name` and `description` into **every single chat thread**.

PRISM divides skills into three tiers:

| Tier | Location | Startup Token Cost | What Belongs Here |
| :--- | :--- | :--- | :--- |
| **Tier 0: Global Active** | `~/.gemini/config/skills/`, `~/.claude/skills/` | ~25–45 tokens/skill | `prism` + at most 4–6 universal daily skills |
| **Tier 1: Workspace Symlink** | `<repo>/.agents/skills/` | ~25–45 tokens (only in that repo) | Stack-specific skills needed for that repository |
| **Tier 2: Cold Vault** | `~/.agents/vault/` | **0 startup tokens** | All other specialist, seasonal, or domain skills (50–500+) |

Because `scripts/build_index.py` indexes `~/.agents/vault/` into `references/_INDEX.md` and `~/.agents/prism_index.json`, vaulted skills remain 100% discoverable on demand while costing zero startup context.

---

## Layer 2: SDO/CSO Hygiene & Core-Size Ratchet (`audit_skills.py`)

Combines empirical rules from `obra/superpowers` and `rebelytics/one-skill-to-rule-them-all`:

1. **SDO Trigger-Only Descriptions:** Frontmatter `description:` must start with `"Use when..."`, remain `< 350 characters` (hard max `500`), and **never summarize the workflow steps** (preventing the LLM from taking the description as a shortcut instead of reading `SKILL.md`).
2. **20,000-Byte Compaction Cliff:** Harnesses truncate re-attached skills at `20,000 characters` after context compaction. PRISM enforces `< 20,000 bytes` on every `SKILL.md`.
3. **One-Way Core-Size Ratchet (`.core-ceiling`):** Locks the line count of `SKILL.md` and `references/ceilings.txt`. If a file grows past its ceiling, validation fails; if a file is trimmed by more than 3 lines, validation prompts you to lower the ceiling to lock in the savings.
4. **Static Link & Residue Gate:** Verifies every relative `references/*` and `scripts/*` path cited in `SKILL.md` exists on disk, and blocks `@path` force-load syntax or edit residue.

---

## Layer 3: Dual-Mode Triage Routing (`route_task.py` & `_INDEX.md`)

PRISM avoids double-hop routing overhead by supporting two complementary modes:

- **Mode A — Portable Hub-and-Spoke (Default, Zero Hooks Required):**
  Works identically across Antigravity, Claude Code, Claude Desktop, and OpenAI Codex. When a specialized task arrives that isn't covered by Tier 0, the agent reads [references/_INDEX.md](_INDEX.md) (or runs `python3 scripts/prism.py route "<prompt>"`) and loads the winning `SKILL.md` directly from `~/.agents/vault/`.
- **Mode B — PreInvocation / UserPromptSubmit Hook Mode (Optional):**
  Runs `route_task.py` in `< 50ms` before the model's turn and injects an `ephemeralMessage` route card only when confidence exceeds the evidence threshold (`score >= 4.0`).

---

## Layer 4: Subagent Context Firewall (`invoke_subagent`)

Loading a skill with 25 KB of reference manuals into the main chat thread pollutes the conversation history for all subsequent turns.

PRISM calculates each skill's **Total Package Weight** (`SKILL.md` + `references/` + `scripts/`):
- **`INLINE` (`< 8 KB` total weight):** Read and execute directly in the main thread.
- **`SUBAGENT_FIREWALL` (`>= 8 KB` total weight or multi-step audit):** Delegate execution to a subagent (`invoke_subagent`) using the pre-generated **Subagent Dispatch Brief**, returning only the verified result summary to the main thread.
