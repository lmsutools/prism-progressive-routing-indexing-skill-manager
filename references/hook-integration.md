# Optional Hook Integration Guide (`hooks.json`)

By default, PRISM operates in **Hybrid Portable Mode**: skills in the Cold Vault (`~/.agents/vault/`) are indexed in [references/_INDEX.md](_INDEX.md) and routed on demand with zero background hooks.

If you want **automatic pre-turn route cards** injected whenever a prompt strongly matches a vaulted or active skill, generate and install the lifecycle hook for your harness.

---

## 1. Antigravity (`~/.gemini/config/hooks.json` or `.agents/hooks.json`)

Generate the exact JSON configuration with:
```bash
python3 scripts/prism.py hooks --harness antigravity
```

This configures:
- **`SessionStart`**: Rebuilds `~/.agents/prism_index.json` and `references/_INDEX.md` silently in the background when a session begins.
- **`PreInvocation`**: Runs `route_task.py --hook antigravity` (`< 50ms`). If a skill matches with high confidence (`score >= 4.0`), injects a transient `ephemeralMessage` Route Card for that turn only (automatically dropped after the turn so it never bloats history!).

---

## 2. Claude Code (`~/.claude/settings.json`)

Generate the Claude Code hook snippet with:
```bash
python3 scripts/prism.py hooks --harness claude
```

This binds `route_task.py --hook claude` to `UserPromptSubmit`, injecting `additionalContext` before the first tool call when a high-confidence match is found.

---

## 3. Disabling or Bypassing the Hook

- Set `"enabled": false` under `"prism-router"` in `hooks.json` to pause auto-routing at any time.
- Conversational prompts (`< 4 words` or lacking technical evidence tokens) automatically return `{}` (total silence).
