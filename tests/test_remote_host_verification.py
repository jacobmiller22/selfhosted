#!/usr/bin/env python3
"""
Unit tests validating Remote Host Verification Protocol & AI Directives.
Verifies topology mapping, root AGENTS/GEMINI instructions, Cursor rules,
and folder-level AI instructions for all services.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRemoteHostVerificationArchitecture(unittest.TestCase):
    def test_infrastructure_topology_exists_and_contains_core_services(self):
        topology_file = REPO_ROOT / "docs" / "INFRASTRUCTURE_TOPOLOGY.md"
        self.assertTrue(topology_file.exists(), "docs/INFRASTRUCTURE_TOPOLOGY.md must exist")

        content = topology_file.read_text(encoding="utf-8")
        self.assertIn("bjorn", content)
        self.assertIn("actual", content)
        self.assertIn("homeassistant", content)
        self.assertIn("vaultwarden", content)
        self.assertIn("nginx-proxy-manager", content)
        self.assertIn("obsidian", content)
        self.assertIn("reiner-cam", content)
        self.assertIn("Backblaze B2", content)
        self.assertIn("secure-backup", content)
        self.assertIn("Tailscale MagicDNS", content)
        self.assertIn("ssh bjorn", content)

    def test_root_agents_directives(self):
        agents_file = REPO_ROOT / "AGENTS.md"
        self.assertTrue(agents_file.exists(), "Root AGENTS.md must exist")

        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("Remote-First Operational Rule", content)
        self.assertIn("Remote Host Verification Protocol", content)
        self.assertIn("ssh bjorn", content)
        self.assertIn("Worktrunk (`wt`)", content)
        self.assertIn("Zero Untracked Work Protocol", content)
        self.assertIn("Secret Hygiene", content)

    def test_root_gemini_directives(self):
        gemini_file = REPO_ROOT / "GEMINI.md"
        self.assertTrue(gemini_file.exists(), "Root GEMINI.md must exist")

        content = gemini_file.read_text(encoding="utf-8")
        self.assertIn("Remote-First Operational Rule", content)
        self.assertIn("Remote Host Verification Protocol", content)
        self.assertIn("ssh <target-host>", content)
        self.assertIn("Worktrunk (`wt`)", content)
        self.assertIn("Zero Untracked Work Protocol (`pm`)", content)

    def test_cursor_rules_exist_and_enforce_remote_verification(self):
        cursorrules = REPO_ROOT / ".cursorrules"
        self.assertTrue(cursorrules.exists(), ".cursorrules must exist in repo root")
        cr_content = cursorrules.read_text(encoding="utf-8")
        self.assertIn("Remote-First Operational Directives", cr_content)
        self.assertIn("Remote Host Verification", cr_content)
        self.assertIn("ssh <target-host>", cr_content)

        mdc_rule = REPO_ROOT / ".cursor" / "rules" / "remote-host-verification.mdc"
        self.assertTrue(mdc_rule.exists(), ".cursor/rules/remote-host-verification.mdc must exist")
        mdc_content = mdc_rule.read_text(encoding="utf-8")
        self.assertIn("Remote Host Verification Protocol", mdc_content)
        self.assertIn("ssh <target-host>", mdc_content)

    def test_folder_level_agents_directives(self):
        services = [
            "actual",
            "homeassistant",
            "vaultwarden",
            "nginx-proxy-manager",
            "obsidian",
            "reiner-cam",
            "tools/backup-runner"
        ]

        for service in services:
            agents_file = REPO_ROOT / service / "AGENTS.md"
            self.assertTrue(agents_file.exists(), f"{service}/AGENTS.md must exist")

            content = agents_file.read_text(encoding="utf-8")
            self.assertIn("bjorn", content, f"{service}/AGENTS.md must specify target host bjorn")
            self.assertIn("ssh", content, f"{service}/AGENTS.md must document ssh command pattern")

    def test_specific_service_nuances(self):
        # Actual Budget
        actual_content = (REPO_ROOT / "actual" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("5006", actual_content)
        self.assertIn("3080", actual_content)
        self.assertIn("auto-categorizer", actual_content)

        # Home Assistant
        ha_content = (REPO_ROOT / "homeassistant" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("network_mode: host", ha_content)
        self.assertIn("8123", ha_content)
        self.assertIn("WebSockets", ha_content)

        # Vaultwarden
        vw_content = (REPO_ROOT / "vaultwarden" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("7277", vw_content)
        self.assertIn("rsa_key.pem", vw_content)
        self.assertIn("600", vw_content)

        # Nginx Proxy Manager
        npm_content = (REPO_ROOT / "nginx-proxy-manager" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("81", npm_content)
        self.assertIn("/etc/letsencrypt", npm_content)

        # Backup Runner
        backup_content = (REPO_ROOT / "tools" / "backup-runner" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("AES-256-CBC", backup_content)
        self.assertIn("PBKDF2", backup_content)
        self.assertIn("secure-backup", backup_content)


if __name__ == "__main__":
    unittest.main()
