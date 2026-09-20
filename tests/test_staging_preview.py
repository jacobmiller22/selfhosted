#!/usr/bin/env python3
"""
Unit and integration tests for Ephemeral Staging Interactive Preview CLI
(tools/preview.sh).

Verifies:
1. Script presence and executable permissions.
2. CLI help flags, options parsing, argument validation, and error reporting.
3. Service normalization and port mappings (Actual Budget -> 5006, Vaultwarden -> 7278).
4. Deterministic --dry-run simulation plan output for both supported services.
5. Flag permutations (--reset, --skip-hydrate, --no-open, --port, --timeout).
"""

import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "preview.sh"


class TestStagingPreviewCLI(unittest.TestCase):
    """Test CLI argument parsing, help, and error handling."""

    def test_script_exists_and_is_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")

    def test_cli_help_flags(self):
        for flag in ["-h", "--help"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0, f"Help flag {flag} should exit 0")
            self.assertIn("Usage:", res.stdout)
            self.assertIn("actual", res.stdout)
            self.assertIn("vaultwarden", res.stdout)
            self.assertIn("--host", res.stdout)
            self.assertIn("--port", res.stdout)
            self.assertIn("--timeout", res.stdout)
            self.assertIn("--skip-hydrate", res.stdout)
            self.assertIn("--reset", res.stdout)
            self.assertIn("--no-open", res.stdout)
            self.assertIn("--dry-run", res.stdout)

    def test_missing_service_argument(self):
        res = subprocess.run(
            [str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Missing required service name", res.stderr)

    def test_unsupported_service_argument(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "invalid_service"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown option: invalid_service", res.stderr)

    def test_invalid_timeout_argument(self):
        for bad_val in ["-10", "abc", "0"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "actual", "--timeout", bad_val],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("Timeout must be a positive integer", res.stderr)

    def test_invalid_local_port_argument(self):
        for bad_port in ["80", "70000", "xyz"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "actual", "--port", bad_port],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("Local port must be an integer between 1025 and 65534", res.stderr)


class TestStagingPreviewDryRun(unittest.TestCase):
    """Test deterministic dry-run simulation execution plans."""

    def test_dry_run_actual_budget(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Dry-run should exit 0. Output:\n{res.stderr}")
        self.assertIn("[DRY-RUN] Ephemeral Staging Interactive Preview Simulation", res.stdout)
        self.assertIn("actual (Actual Budget)", res.stdout)
        self.assertIn("actual-server-staging", res.stdout)
        self.assertIn("Staging Remote Port:   5006", res.stdout)
        self.assertIn("Local Forwarded Port:  5006", res.stdout)
        self.assertIn("Local Preview URL:     http://localhost:5006", res.stdout)
        self.assertIn("Auto-Open Browser:     true", res.stdout)
        self.assertIn("Step 1: Pre-flight Remote Host Verification (RHVP)", res.stdout)
        self.assertIn("Step 2: Production Snapshot Hydration & Staging Boot", res.stdout)
        self.assertIn("Step 3: Remote Staging Health Probe", res.stdout)
        self.assertIn("Step 4: Ephemeral SSH Port-Forward Tunnel", res.stdout)
        self.assertIn("Step 5: Remote Safety Watchdog Timer", res.stdout)
        self.assertIn("Step 6: Browser Launch", res.stdout)
        self.assertIn("Step 7: Teardown on Exit", res.stdout)

    def test_dry_run_vaultwarden(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "vaultwarden", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Dry-run should exit 0. Output:\n{res.stderr}")
        self.assertIn("[DRY-RUN] Ephemeral Staging Interactive Preview Simulation", res.stdout)
        self.assertIn("vaultwarden (Vaultwarden)", res.stdout)
        self.assertIn("vaultwarden-staging", res.stdout)
        self.assertIn("Staging Remote Port:   7278", res.stdout)
        self.assertIn("Local Forwarded Port:  7278", res.stdout)
        self.assertIn("Local Preview URL:     http://localhost:7278", res.stdout)
        self.assertIn("vaultwarden/compose.yml", res.stdout)

    def test_dry_run_service_option_flag(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "actual", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("actual (Actual Budget)", res.stdout)

    def test_dry_run_no_open_flag(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run", "--no-open"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Auto-Open Browser:     false", res.stdout)
        self.assertIn("browser launch suppressed (--no-open flag set)", res.stdout)

    def test_dry_run_custom_port(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run", "--port", "5099"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Local Forwarded Port:  5099", res.stdout)
        self.assertIn("Local Preview URL:     http://localhost:5099", res.stdout)
        self.assertIn("5099:localhost:5006", res.stdout)

    def test_dry_run_custom_timeout(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run", "--timeout", "120"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Watchdog Timeout:      120 minutes", res.stdout)
        self.assertIn("Remote Safety Watchdog Timer (120m)", res.stdout)

    def test_dry_run_reset_flag(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run", "--reset"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Force Reset Volume:    true", res.stdout)
        self.assertIn("--reset actual --start", res.stdout)

    def test_dry_run_skip_hydrate_flag(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run", "--skip-hydrate"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Skip Hydration:        true", res.stdout)

    def test_dry_run_local_host(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "actual", "--dry-run", "--host", "localhost"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("local execution (host: localhost)", res.stdout)
        self.assertIn("direct local port binding on http://localhost:5006", res.stdout)


if __name__ == "__main__":
    unittest.main()
