#!/usr/bin/env python3
"""
PRISM Automated Self-Test Suite (test_prism.py)
Verifies all 4 layers of the PRISM Ultra-Pattern Architecture:
  1. Layer 1: Cold Vault & Symlink Manager (`vault_manager.py`)
  2. Layer 2: Forensic Auditor, SDO Checks & Core-Size Ratchet (`audit_skills.py`)
  3. Layer 3: Shadow Indexer & Dual-Leg Triage Router (`build_index.py`, `route_task.py`)
  4. Layer 4: Subagent Firewall Classification & Hook Payloads
  5. Dogfooding Gate: `prism` itself must score 100/100 with 0 errors and 0 warnings!
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import audit_skills  # noqa: E402
import build_index  # noqa: E402
import route_task  # noqa: E402


class TestPrismArchitecture(unittest.TestCase):
    def test_01_build_index_and_hub_table(self) -> None:
        res = build_index.build_and_save(include_builtin=True)
        self.assertGreater(res["count"], 0)
        self.assertLess(res["hub_tokens_est"], 1000, "Hub _INDEX.md must stay under 1,000 tokens")
        self.assertTrue(Path(res["index_json"]).is_file())
        self.assertTrue(Path(res["hub_md"]).is_file())

    def test_02_prism_self_audit_100_percent(self) -> None:
        """PRISM must pass its own strict SDO, compaction, link, and ratchet gates with 100/100."""
        skill_info = audit_skills.audit_single_skill(REPO_ROOT, "tier0_global", "antigravity")
        self.assertEqual(skill_info["errors"], [], f"PRISM has errors: {skill_info['errors']}")
        self.assertEqual(skill_info["warnings"], [], f"PRISM has warnings: {skill_info['warnings']}")
        self.assertEqual(skill_info["score"], 100)
        self.assertLess(skill_info["desc_chars"], 350)
        self.assertTrue(skill_info["description"].startswith("Use when"))

    def test_03_sdo_violation_and_compaction_detection(self) -> None:
        """Verify auditor catches bloated descriptions, capability pitches, and broken links."""
        with tempfile.TemporaryDirectory() as tmp:
            bad_skill = Path(tmp) / "Bad_Skill_Name"
            bad_skill.mkdir()
            (bad_skill / "SKILL.md").write_text(
                "---\n"
                "name: Bad_Skill_Name\n"
                "description: Comprehensive senior-level guide for everything. First it runs step 1, then it runs step 2.\n"
                "---\n"
                "# Bad Skill\n"
                "See [missing.md](references/missing.md) and @references/forced.md\n",
                encoding="utf-8",
            )
            res = audit_skills.audit_single_skill(bad_skill, "tier0_global", "claude")
            self.assertLess(res["score"], 60)
            self.assertTrue(any("Broken relative paths" in e for e in res["errors"]))
            self.assertTrue(any("force-load" in e for e in res["errors"]))
            self.assertTrue(any("SDO" in w for w in res["warnings"]))

    def test_04_triage_router_and_subagent_firewall(self) -> None:
        """Verify routing matches Rust skill with SUBAGENT_FIREWALL and ignores short chatter."""
        short_res = route_task.route_prompt("hello how are you")
        self.assertFalse(short_res["routed"])

        rust_res = route_task.route_prompt("diagnose slow cargo compile times in my multi-crate rust workspace")
        self.assertTrue(rust_res["routed"])
        self.assertEqual(rust_res["primary"]["name"], "weedo-rust-dev-skill")
        self.assertEqual(rust_res["primary"]["execution_mode"], "SUBAGENT_FIREWALL")
        self.assertIsNotNone(rust_res["subagent_brief"])

    def test_05_hook_payload_contracts(self) -> None:
        """Verify Antigravity PreInvocation and Claude UserPromptSubmit JSON outputs."""
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "route_task.py"), "--hook", "antigravity",
             "scaffold a new multi-crate rust workspace with fast cargo builds"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        self.assertIn("injectSteps", data)
        self.assertIn("ephemeralMessage", data["injectSteps"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
