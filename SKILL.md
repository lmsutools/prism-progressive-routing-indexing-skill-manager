---
name: prism
description: >-
  Use when auditing, optimizing, or organizing AI agent skills, fixing
  description or context window bloat, managing the Cold Vault or skill
  symlinks, detecting trigger collisions, or routing tasks across installed and
  vaulted skills.
---

# PRISM — Progressive Routing, Indexing & Skill Manager

Goal: eliminate startup token bloat, semantic trigger collisions, and the 20 KB compaction cliff across **Antigravity, Claude Code, and OpenAI Codex** by enforcing the **4-Layer Ultra-Pattern Architecture** ([ultra-architecture.md](references/ultra-architecture.md)).

## Choose the Workflow

| Situation | Action / Workflow |
| :--- | :--- |
| Audit installed skills for bloat, SDO issues, or collisions | **Workflow A: Forensic Audit** |
| Fix bloated descriptions or split skills `> 20 KB` | **Workflow B: SDO Optimize & Ratchet** |
| Park unused skills in Cold Vault or symlink to a project | **Workflow C: Cold Vault & Tiering** |
| Route a complex task to a Vaulted/Active skill + Subagent | **Workflow D: Triage Route & Subagent Firewall** |
| Configure optional `PreInvocation` / `UserPromptSubmit` hooks | Read [hook-integration.md](references/hook-integration.md) |

---

## Workflow A: Forensic Audit (`audit`)

1. Run the forensic auditor across all discovered skill directories:
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/prism.py audit --include-builtin
   ```
   *(If running from the repository root, use `python3 scripts/prism.py audit` or [audit_skills.py](scripts/audit_skills.py)).*
2. Review the 5 automated gates in the report:
   - **Startup Token Tax:** Total tokens injected into every chat thread by Tier 0 (Global) and Tier 1 (Workspace) skills.
   - **SDO Frontmatter Gate:** Flags descriptions that exceed `350–500 chars`, fail to start with `"Use when..."`, or summarize workflows.
   - **Compaction Cliff Gate:** Flags `SKILL.md` files approaching or exceeding `20,000 bytes`.
   - **Ratchet & Link Gate:** Verifies `.core-ceiling`, `references/ceilings.txt`, and every cited `references/*` or `scripts/*` path.
   - **Semantic Collision Detector:** Identifies pairs of skills with `>= 32%` trigger keyword overlap.

---

## Workflow B: SDO Optimize & Ratchet (`optimize`)

When Workflow A reports warnings or errors on a skill:

1. Read [sdo-refactoring-guide.md](references/sdo-refactoring-guide.md) for the positive structural templates.
2. **Rewrite bloated descriptions:** Replace capability summaries with a crisp `"Use when..."` trigger clause under `350 characters` (`< 55 words`). Never summarize step-by-step workflows in `description:`.
3. **Split oversized bodies:** Move reference tables, deep playbooks, and code templates (`> 40 lines`) into `references/<topic>.md` and link to them with standard Markdown links (`[<topic>.md](references/<topic>.md)` — never `@` syntax).
4. **Lock the Core-Size Ratchet** so future edits cannot silently re-bloat the file:
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/audit_skills.py /path/to/skill --lock-ratchet
   ```
5. Re-run `prism.py audit /path/to/skill --strict` and verify a `100/100` score.

---

## Workflow C: Cold Vault & Multi-Harness Tiering (`vault`)

Keep **Tier 0 (Global Active)** limited to `prism` + at most 4–6 daily universal skills. Keep everything else in **Tier 2 (Cold Vault: `~/.agents/vault/`)** at **0 startup tokens**:

1. Inspect current skill topology across Antigravity, Claude, Codex, Workspace, and Vault:
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/vault_manager.py status
   ```
2. **Park** a specialized or rarely used global skill into the Cold Vault (0 startup tax, still routable via PRISM):
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/vault_manager.py park <skill-name>
   ```
3. **Activate** a vaulted skill into a specific project workspace (`.agents/skills/`) or harness (`antigravity`, `claude`, `codex`, `all`):
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/vault_manager.py activate <skill-name> --target workspace
   ```
4. Rebuild the shadow index (`~/.agents/prism_index.json`) and compact Hub table ([_INDEX.md](references/_INDEX.md)):
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/build_index.py
   ```

---

## Workflow D: Triage Route & Subagent Firewall (`route`)

When executing a specialized task or looking up a skill in the Cold Vault:

1. Read the compact Hub table [_INDEX.md](references/_INDEX.md) or run the deterministic Dual-Leg Router ([route_task.py](scripts/route_task.py)):
   ```bash
   python3 ~/.gemini/config/skills/prism/scripts/route_task.py "<user task description>"
   ```
2. Follow the emitted **PRISM Route Card**:
   - **Leg 1 (Domain Skill):** Primary technical playbook to load.
   - **Leg 2 (Process Skill):** Companion methodology (e.g., debugging, TDD, planning) if applicable.
   - **Execution Mode:**
     - `INLINE` (`< 8 KB` package): Read the target `SKILL.md` directly in the current conversation.
     - `SUBAGENT_FIREWALL` (`>= 8 KB` package or deep audit): Protect the main context window by delegating execution via `invoke_subagent` using the Route Card's pre-built **Subagent Brief**.
