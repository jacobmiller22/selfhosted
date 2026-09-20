#!/usr/bin/env python3
"""
Unit tests validating Disaster Recovery Exercises runbook, staging verification procedures,
RTO/RPO SLAs, and documentation cross-references across RESTORE.md, BACKUP_ARCHITECTURE.md,
and README.md.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestDrExerciseDocs(unittest.TestCase):
    def setUp(self):
        self.dr_doc = REPO_ROOT / "docs" / "DISASTER_RECOVERY_EXERCISES.md"
        self.restore_doc = REPO_ROOT / "docs" / "RESTORE.md"
        self.backup_arch_doc = REPO_ROOT / "docs" / "BACKUP_ARCHITECTURE.md"
        self.readme = REPO_ROOT / "README.md"

    def test_dr_exercise_doc_exists(self):
        self.assertTrue(self.dr_doc.exists(), "docs/DISASTER_RECOVERY_EXERCISES.md must exist")

    def test_homelab_axioms_present(self):
        content = self.dr_doc.read_text(encoding="utf-8")
        self.assertIn("Axiom 1: Maximum Server Uptime", content)
        self.assertIn("Axiom 2: Zero Tolerance for Data Loss", content)
        self.assertIn("Axiom 3: Minimal Maintenance Burden", content)
        self.assertIn("Axiom 4: Single-Server Catastrophe Risk", content)
        self.assertIn("bjorn", content)

    def test_sla_definitions_present(self):
        content = self.dr_doc.read_text(encoding="utf-8")
        # RPO
        self.assertIn("Recovery Point Objective (RPO)", content)
        self.assertIn("< 24 Hours", content)
        self.assertIn("26 Hours", content)
        # RTO
        self.assertIn("Recovery Time Objective (RTO)", content)
        self.assertIn("< 5 Minutes", content)
        self.assertIn("< 10 Minutes", content)
        self.assertIn("< 30 Minutes", content)
        # Service loss tolerances
        self.assertIn("Actual Budget", content)
        self.assertIn("Vaultwarden", content)
        self.assertIn("Home Assistant", content)
        self.assertIn("Nginx Proxy Manager", content)
        self.assertIn("Obsidian LiveSync", content)

    def test_step_by_step_procedures_present(self):
        content = self.dr_doc.read_text(encoding="utf-8")
        # Automated drill on bjorn
        self.assertIn("Procedure A: Automated DR Drill Execution", content)
        self.assertIn("dr-drill.sh --service all --dry-run", content)
        self.assertIn("dr-drill.sh --service all --fail-on-rpo", content)
        self.assertIn("/var/log/dr-drill.log", content)

        # Manual drill on local machine
        self.assertIn("Procedure B: Manual Failover Drill", content)
        self.assertIn("BACKUP_PASSPHRASE", content)
        self.assertIn("Salted__", content)
        self.assertIn("verify-db-integrity.sh", content)
        self.assertIn("staging-smoke-test.sh", content)

    def test_failure_triage_and_exit_codes(self):
        content = self.dr_doc.read_text(encoding="utf-8")
        for code, name in [
            ("0", "EXIT_OK"),
            ("1", "EXIT_USAGE_ERR"),
            ("2", "EXIT_PULL_FAIL"),
            ("3", "EXIT_INTEGRITY_FAIL"),
            ("4", "EXIT_SMOKE_FAIL"),
            ("5", "EXIT_RPO_FAIL"),
            ("6", "EXIT_PING_FAIL"),
        ]:
            self.assertIn(code, content)
            self.assertIn(name, content)

        self.assertIn("DISCORD_WEBHOOK_URL", content)
        self.assertIn("HEALTHCHECK_DR_PING_URL", content)

    def test_restore_md_integration(self):
        content = self.restore_doc.read_text(encoding="utf-8")
        self.assertIn("docs/DISASTER_RECOVERY_EXERCISES.md", content)
        self.assertIn("dr-drill.sh", content)
        self.assertIn("--fail-on-rpo", content)
        self.assertIn("Recovery Point Objective (RPO)", content)
        self.assertIn("Recovery Time Objective (RTO)", content)

    def test_backup_architecture_md_integration(self):
        content = self.backup_arch_doc.read_text(encoding="utf-8")
        self.assertIn("Disaster Recovery Verification Cycle & Alerting Topology", content)
        self.assertIn("dr-drill.sh", content)
        self.assertIn("HEALTHCHECK_DR_PING_URL", content)
        self.assertIn("DISCORD_WEBHOOK_URL", content)
        self.assertIn("DISASTER_RECOVERY_EXERCISES.md", content)

    def test_readme_integration_and_relative_links(self):
        content = self.readme.read_text(encoding="utf-8")
        self.assertIn("docs/DISASTER_RECOVERY_EXERCISES.md", content)

        links = re.findall(r'\[.*?\]\((docs/[^)#]+)\)', content)
        for link in links:
            target = REPO_ROOT / link
            self.assertTrue(target.exists(), f"Target '{link}' referenced in README.md must exist")


if __name__ == "__main__":
    unittest.main()
