#!/usr/bin/env python3
"""
Unit tests validating Remote Host Verification Protocol & AI Directives.
Verifies topology mapping, root AGENTS/GEMINI instructions, Cursor rules,
and folder-level AI instructions for all services.
"""

import os
import subprocess
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

    def test_root_agents_odvp_directives(self):
        agents_file = REPO_ROOT / "AGENTS.md"
        self.assertTrue(agents_file.exists(), "Root AGENTS.md must exist")
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("Outside-In Remote Deployment Verification Protocol (ODVP)", content)
        self.assertIn("The 5-Layer Verification Model", content)
        self.assertIn("L1", content)
        self.assertIn("Container Stability & Healthcheck Latch", content)
        self.assertIn("L2", content)
        self.assertIn("Internal Business Logic & Data Probe", content)
        self.assertIn("L3", content)
        self.assertIn("Reverse Proxy & Bridge Network", content)
        self.assertIn("L4", content)
        self.assertIn("Outside DNS & TLS Handshake Validation", content)
        self.assertIn("L5", content)
        self.assertIn("Outside-In HTTPS Egress Probe", content)
        self.assertIn("tools/verify-deployment/verify_service.sh", content)

    def test_root_gemini_odvp_directives(self):
        gemini_file = REPO_ROOT / "GEMINI.md"
        self.assertTrue(gemini_file.exists(), "Root GEMINI.md must exist")
        content = gemini_file.read_text(encoding="utf-8")
        self.assertIn("Outside-In Remote Deployment Verification Protocol (ODVP)", content)
        self.assertIn("L1", content)
        self.assertIn("Container Stability & Healthcheck Latch", content)
        self.assertIn("L2", content)
        self.assertIn("Internal Business Logic & Data Probe", content)
        self.assertIn("L3", content)
        self.assertIn("Reverse Proxy & Bridge Network Verification", content)
        self.assertIn("L4", content)
        self.assertIn("Outside DNS & TLS Handshake Validation", content)
        self.assertIn("L5", content)
        self.assertIn("Outside-In HTTPS Egress Probe", content)
        self.assertIn("tools/verify-deployment/verify_service.sh", content)

    def test_cursor_rules_odvp_directives(self):
        mdc_rule = REPO_ROOT / ".cursor" / "rules" / "remote-host-verification.mdc"
        self.assertTrue(mdc_rule.exists(), ".cursor/rules/remote-host-verification.mdc must exist")
        content = mdc_rule.read_text(encoding="utf-8")
        self.assertIn("Outside-In Remote Deployment Verification Protocol (ODVP)", content)
        self.assertIn("L1", content)
        self.assertIn("L2", content)
        self.assertIn("L3", content)
        self.assertIn("L4", content)
        self.assertIn("L5", content)
        self.assertIn("tools/verify-deployment/verify_service.sh", content)

    def test_verify_deployment_script_attributes_and_help(self):
        script_path = REPO_ROOT / "tools" / "verify-deployment" / "verify_service.sh"
        self.assertTrue(script_path.exists(), "tools/verify-deployment/verify_service.sh must exist")
        self.assertTrue(os.access(script_path, os.X_OK), "tools/verify-deployment/verify_service.sh must be executable")

        for flag in ["-h", "--help"]:
            res = subprocess.run(
                [str(script_path), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0, f"Help flag {flag} should exit 0")
            self.assertIn("Usage:", res.stdout)
            self.assertIn("ODVP", res.stdout)
            self.assertIn("L1", res.stdout)
            self.assertIn("L2", res.stdout)
            self.assertIn("L3", res.stdout)
            self.assertIn("L4", res.stdout)
            self.assertIn("L5", res.stdout)
            self.assertIn("--host", res.stdout)
            self.assertIn("--service", res.stdout)
            self.assertIn("--internal-port", res.stdout)
            self.assertIn("--url", res.stdout)
            self.assertIn("--skip-remote", res.stdout)
            self.assertIn("--dry-run", res.stdout)

    def test_verify_deployment_script_dry_run_modes(self):
        script_path = REPO_ROOT / "tools" / "verify-deployment" / "verify_service.sh"

        # Full dry-run
        res_full = subprocess.run(
            [
                str(script_path),
                "--host", "bjorn",
                "--service", "actual",
                "--internal-port", "5006",
                "--url", "https://actual.cloud.jacobmiller22.com",
                "--dry-run"
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_full.returncode, 0)
        self.assertIn("[DRY-RUN]", res_full.stdout)
        self.assertIn("[L1]", res_full.stdout)
        self.assertIn("[L2]", res_full.stdout)
        self.assertIn("[L3]", res_full.stdout)
        self.assertIn("[L4]", res_full.stdout)
        self.assertIn("[L5]", res_full.stdout)

        # Skip remote dry-run
        res_skip = subprocess.run(
            [
                str(script_path),
                "--skip-remote",
                "--url", "https://actual.cloud.jacobmiller22.com",
                "--dry-run"
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_skip.returncode, 0)
        self.assertIn("Remote checks skipped (--skip-remote)", res_skip.stdout)
        self.assertIn("[L4]", res_skip.stdout)
        self.assertIn("[L5]", res_skip.stdout)

    def test_verify_deployment_script_error_handling(self):
        script_path = REPO_ROOT / "tools" / "verify-deployment" / "verify_service.sh"

        # No arguments provided
        res_no_args = subprocess.run(
            [str(script_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res_no_args.returncode, 0)
        self.assertIn("Error:", res_no_args.stderr)

        # Unknown flag
        res_unknown = subprocess.run(
            [str(script_path), "--unrecognized-option"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res_unknown.returncode, 0)
        self.assertIn("Error: Unknown argument", res_unknown.stderr)

        # Skip-remote without URL
        res_skip_no_url = subprocess.run(
            [str(script_path), "--skip-remote", "--service", "actual"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res_skip_no_url.returncode, 0)
        self.assertIn("Error:", res_skip_no_url.stderr)

    def test_verify_deployment_script_layer_logic_coverage(self):
        script_path = REPO_ROOT / "tools" / "verify-deployment" / "verify_service.sh"
        content = script_path.read_text(encoding="utf-8")

        # Check L1 logic
        self.assertIn("docker inspect", content)
        self.assertIn("State.Status", content)
        self.assertIn("State.RestartCount", content)
        self.assertIn("State.Health", content)

        # Check L2 logic
        self.assertIn("localhost", content)
        self.assertIn("curl", content)

        # Check L3 logic
        self.assertIn("NetworkSettings.Networks", content)

        # Check L4 logic
        self.assertIn("dig", content)
        self.assertIn("curl", content)

        # Check L5 logic
        self.assertIn("502", content)
        self.assertIn("504", content)
        self.assertIn("200", content)


if __name__ == "__main__":
    unittest.main()

