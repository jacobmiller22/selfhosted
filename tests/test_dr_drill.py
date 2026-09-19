#!/usr/bin/env python3
"""
Unit tests validating Disaster Recovery (DR) Automated Drill Orchestrator (dr-drill.sh).
Tests CLI flags, syntax, argument validation, dry-run simulation, RTO/RPO calculation helpers,
SLA threshold alerts, Discord webhook failure traps, and Healthchecks.io heartbeat pings.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "backup-dr" / "dr-drill.sh"
README_PATH = REPO_ROOT / "tools" / "backup-dr" / "README.md"


class TestDRDrillBasics(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")

    def test_shellcheck_clean(self):
        shellcheck_bin = shutil.which("shellcheck")
        if not shellcheck_bin:
            self.skipTest("shellcheck binary not found on PATH")

        res = subprocess.run(
            [shellcheck_bin, "--severity=warning", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"ShellCheck produced warnings:\n{res.stderr}\n{res.stdout}")

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
            self.assertIn("--service", res.stdout)
            self.assertIn("--source", res.stdout)
            self.assertIn("--backup-dir", res.stdout)
            self.assertIn("--data-dir", res.stdout)
            self.assertIn("--skip-pull", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--host", res.stdout)
            self.assertIn("--webhook-url", res.stdout)
            self.assertIn("--ping-url", res.stdout)
            self.assertIn("--rpo-max-hours", res.stdout)
            self.assertIn("--fail-on-rpo", res.stdout)
            self.assertIn("--calculate-rpo", res.stdout)
            self.assertIn("--calculate-rto", res.stdout)
            self.assertIn("Exit Codes:", res.stdout)
            self.assertIn("0", res.stdout)
            self.assertIn("1", res.stdout)
            self.assertIn("2", res.stdout)
            self.assertIn("3", res.stdout)
            self.assertIn("4", res.stdout)
            self.assertIn("5", res.stdout)
            self.assertIn("6", res.stdout)

    def test_readme_documentation_coverage(self):
        self.assertTrue(README_PATH.exists(), f"{README_PATH} must exist")
        content = README_PATH.read_text(encoding="utf-8")
        self.assertIn("dr-drill.sh", content)
        self.assertIn("pull-and-decrypt.sh", content)
        self.assertIn("verify-db-integrity.sh", content)
        self.assertIn("staging-smoke-test.sh", content)
        self.assertIn("RTO", content)
        self.assertIn("RPO", content)
        self.assertIn("26 hours", content)
        self.assertIn("DISCORD_WEBHOOK_URL", content)
        self.assertIn("HEALTHCHECK_DR_PING_URL", content)
        self.assertIn("0 3 * * 0", content)


class TestDRDrillCLIValidation(unittest.TestCase):
    def test_invalid_option(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--unknown-flag"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown option", res.stderr)

    def test_missing_option_arguments(self):
        flags = [
            "--service",
            "--source",
            "--backup-dir",
            "--file",
            "--data-dir",
            "--timeout",
            "--webhook-url",
            "--ping-url",
            "--rpo-max-hours",
            "--calculate-rpo",
        ]
        for flag in flags:
            res = subprocess.run(
                [str(SCRIPT_PATH), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1, f"{flag} without value should exit 1")
            self.assertIn("Missing value", res.stderr)

    def test_unsupported_service(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--service", "unsupported_service"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unsupported service", res.stderr)

    def test_invalid_timeout(self):
        for bad_timeout in ["-5", "0", "abc"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--timeout", bad_timeout],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1, f"Timeout '{bad_timeout}' should exit 1")
            self.assertIn("Timeout must be a positive integer", res.stderr)

    def test_invalid_rpo_max_hours(self):
        for bad_hours in ["-1", "0", "xyz"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--rpo-max-hours", bad_hours],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 1, f"RPO hours '{bad_hours}' should exit 1")
            self.assertIn("RPO max hours must be a positive integer", res.stderr)

    def test_skip_pull_validation(self):
        # --skip-pull without --data-dir
        res = subprocess.run(
            [str(SCRIPT_PATH), "--skip-pull"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("--data-dir <path> is required", res.stderr)

        # --skip-pull with nonexistent directory
        res = subprocess.run(
            [str(SCRIPT_PATH), "--skip-pull", "--data-dir", "/tmp/nonexistent_dr_dir_12345"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("does not exist", res.stderr)


class TestDRDrillRTORPOCalculation(unittest.TestCase):
    def test_rto_calculation_helper(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--calculate-rto", "1000", "1045"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("RTO_SECONDS=45", res.stdout)

        # Negative delta clamps to 0
        res2 = subprocess.run(
            [str(SCRIPT_PATH), "--calculate-rto", "2000", "1500"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res2.returncode, 0)
        self.assertIn("RTO_SECONDS=0", res2.stdout)

    def test_rpo_calculation_fresh_backup(self):
        # 2 hours delta (10:00 to 12:00)
        archive_name = "actual-backup-2026-09-18_10-00-00.tar.gz.enc"
        ref_time = "2026-09-18_12-00-00"
        res = subprocess.run(
            [str(SCRIPT_PATH), "--calculate-rpo", archive_name, "--reference-time", ref_time],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("RPO_SECONDS=7200", res.stdout)
        self.assertIn("RPO_HOURS=2", res.stdout)
        self.assertIn("RPO_ALERT=false", res.stdout)

    def test_rpo_calculation_stale_backup_alert(self):
        # 28 hours delta (Sep 17 08:00 to Sep 18 12:00)
        archive_name = "vaultwarden-backup-2026-09-17_08-00-00.tar.gz.enc"
        ref_time = "2026-09-18_12-00-00"
        res = subprocess.run(
            [str(SCRIPT_PATH), "--calculate-rpo", archive_name, "--reference-time", ref_time],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("RPO_SECONDS=100800", res.stdout)
        self.assertIn("RPO_HOURS=28", res.stdout)
        self.assertIn("RPO_ALERT=true", res.stdout)

    def test_rpo_calculation_custom_threshold(self):
        # 14 hours delta
        archive_name = "actual-backup-2026-09-18_00-00-00.tar.gz.enc"
        ref_time = "2026-09-18_14-00-00"

        # With default 26h threshold: no alert
        res_default = subprocess.run(
            [str(SCRIPT_PATH), "--calculate-rpo", archive_name, "--reference-time", ref_time],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_default.returncode, 0)
        self.assertIn("RPO_ALERT=false", res_default.stdout)

        # With custom 12h threshold: alert triggered
        res_custom = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--calculate-rpo",
                archive_name,
                "--reference-time",
                ref_time,
                "--rpo-max-hours",
                "12",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_custom.returncode, 0)
        self.assertIn("RPO_HOURS=14", res_custom.stdout)
        self.assertIn("RPO_ALERT=true", res_custom.stdout)

    def test_rpo_calculation_file_fallback(self):
        with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tf:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--calculate-rpo", tf.name],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("RPO_SECONDS=", res.stdout)
            self.assertIn("RPO_ALERT=false", res.stdout)


class TestDRDrillDryRun(unittest.TestCase):
    def test_dry_run_full_pipeline(self):
        res = subprocess.run(
            [str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Dry-run failed:\n{res.stderr}\n{res.stdout}")
        self.assertIn("Disaster Recovery Automated Drill Orchestrator", res.stdout)
        self.assertIn("Dry-Run Mode:    true", res.stdout)
        self.assertIn("Phase 1: Discovering, pulling, and decrypting backup archives", res.stdout)
        self.assertIn("Phase 2: Verifying database integrity", res.stdout)
        self.assertIn("Phase 3: Running ephemeral staging container smoke tests", res.stdout)
        self.assertIn("Phase 4: Calculating RTO and RPO telemetry metrics", res.stdout)
        self.assertIn("Telemetry & SLA Metrics Summary", res.stdout)
        self.assertIn("RTO (Recovery Time Objective):", res.stdout)
        self.assertIn("RPO (Recovery Point Objective):", res.stdout)
        self.assertIn("Disaster Recovery Drill completed successfully (100% Verified)", res.stdout)

    def test_dry_run_service_filter(self):
        for svc in ["actual", "vaultwarden"]:
            res = subprocess.run(
                [str(SCRIPT_PATH), "--dry-run", "--service", svc],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn(f"Target Service:  {svc}", res.stdout)
            self.assertIn(f"pull-and-decrypt.sh --service {svc}", res.stdout)
            self.assertIn(f"verify-db-integrity.sh --service {svc}", res.stdout)


class TestDRDrillExitTrapAndAlerting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_dr_trap_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_discord_failure_trap_captures_error(self):
        # Create a mock curl that records POST invocations
        mock_curl_log = Path(self.temp_dir) / "curl_calls.log"
        mock_curl = Path(self.temp_dir) / "mock_curl.sh"
        mock_curl.write_text(
            f"""#!/usr/bin/env bash
echo "$@" >> "{mock_curl_log}"
cat >> "{mock_curl_log}"
exit 0
"""
        )
        mock_curl.chmod(0o755)

        # Run drill against nonexistent backup file, with DISCORD_WEBHOOK_URL set
        env = dict(os.environ)
        env["CURL_CMD"] = str(mock_curl)
        env["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/mock_test"

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--service",
                "actual",
                "--source",
                "file",
                "--file",
                "/tmp/nonexistent_archive_dr_test.enc",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )

        # Drill must fail with non-zero exit code
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Disaster recovery drill failed during step: pull-and-decrypt-actual", res.stderr)

        # Verify mock curl received failure embed POST
        self.assertTrue(mock_curl_log.exists(), "Mock curl log must exist")
        log_content = mock_curl_log.read_text(encoding="utf-8")
        self.assertIn("https://discord.com/api/webhooks/mock_test", log_content)
        self.assertIn("Disaster Recovery Drill FAILED", log_content)
        self.assertIn("pull-and-decrypt-actual", log_content)

    def test_healthchecks_ping_on_clean_completion(self):
        mock_curl_log = Path(self.temp_dir) / "curl_ping.log"
        mock_curl = Path(self.temp_dir) / "mock_curl_ping.sh"
        mock_curl.write_text(
            f"""#!/usr/bin/env bash
echo "$@" >> "{mock_curl_log}"
exit 0
"""
        )
        mock_curl.chmod(0o755)

        ping_url = "https://hc-ping.com/99999999-dr-test-uuid"
        env = dict(os.environ)
        env["CURL_CMD"] = str(mock_curl)
        env["HEALTHCHECK_DR_PING_URL"] = ping_url

        # Create dummy pre-decrypted data dir with actual and vaultwarden to allow clean dry-run
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--dry-run",
                "--ping-url",
                ping_url,
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Healthchecks Ping:", res.stdout)

    def test_fail_on_rpo_threshold_breached(self):
        # Create an archive with timestamp older than 26 hours
        old_archive = Path(self.temp_dir) / "actual-backup-2020-01-01_00-00-00.tar.gz.enc"
        old_archive.write_bytes(b"Salted__0123456789abcdef")

        # Running with --fail-on-rpo should exit code 5 (EXIT_RPO_FAIL)
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--file",
                str(old_archive),
                "--dry-run",
                "--fail-on-rpo",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 5)
        self.assertIn("RPO ALERT:", res.stderr)
        self.assertIn("RPO SLA violation", res.stderr)


if __name__ == "__main__":
    unittest.main()
