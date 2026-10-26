# SDO / CSO Refactoring & De-Bloating Recipes

Use this guide during **Workflow B (Optimize & Slim)** when `python3 scripts/prism.py audit` reports warnings or errors on an installed skill.

---

## Recipe 1: Rewriting Bloated or Non-SDO Descriptions

### Why Descriptions Fail
1. **Capability Pitching:** Starting with *"Comprehensive senior-level guide for..."* wastes 10–20 tokens per skill in every chat without adding trigger precision.
2. **The Workflow Shortcut Trap (`obra/superpowers`):** Summarizing *how* the skill works in `description:` causes agents to follow the 1-line summary instead of reading `SKILL.md`.
3. **Buzzword Stuffing:** Listing 30 generic nouns causes false-positive activations and semantic collisions with other skills.

### Positive Structural Template
Every optimized `description:` must follow this exact recipe:

```yaml
description: >-
  Use when <specific user intent or task 1>, <symptom or error condition 2>,
  or <concrete file/technology trigger 3>.
```

### Checklist Before Saving
- [ ] Starts with `Use when...`
- [ ] Total length is `< 350 characters` (`< 55 words`)
- [ ] Contains **zero** step-by-step workflow summaries
- [ ] Names concrete file extensions, CLI tools, or error symptoms if technology-specific

---

## Recipe 2: Splitting a `SKILL.md` Over the 20 KB Compaction Cliff

When `SKILL.md` exceeds `15,000–20,000 bytes`:

1. **Keep in `SKILL.md` (Core Dispatcher, `< 200 lines`):**
   - YAML Frontmatter (`name`, `description`)
   - 2-sentence Goal / Overview
   - Decision table mapping situations to workflows (`## Choose the workflow`)
   - High-level numbered workflow steps with relative Markdown links to `references/` and `scripts/`
2. **Move to `references/<topic>.md`:**
   - Code templates longer than 40 lines
   - Deep API tables, OS-specific troubleshooting matrices, and edge-case catalogs
3. **Replace `@` Links with Standard Markdown Links:**
   - ❌ `@references/api-guide.md` (force-loads into context immediately)
   - ✅ `[api-guide.md](references/api-guide.md)` (loaded on demand only when clicked/read)
4. **Lock the Ratchet:**
   ```bash
   python3 scripts/prism.py audit /path/to/skill --lock-ratchet
   ```

---

## Recipe 3: Resolving Semantic Trigger Collisions

When `audit_skills.py` reports a collision (`overlap >= 32%`) between `Skill A` and `Skill B`:

1. **Differentiate by Artifact or Phase:**
   - Example: If `react-architecture` and `frontend-ui` collide on `react, component, ui`, scope `react-architecture` to *"state management, data fetching, and workspace routing"* and `frontend-ui` to *"visual styling, Tailwind CSS, animations, and layout polish"*.
2. **Park the Less Frequent Skill in the Cold Vault:**
   ```bash
   python3 scripts/prism.py vault park <less-frequent-skill>
   ```
   Parking one of the colliding skills removes it from global startup discovery while keeping it accessible via PRISM's router.
