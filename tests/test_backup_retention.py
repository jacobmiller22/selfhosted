#!/usr/bin/env python3
"""
Unit tests validating Backblaze B2 snapshot retention policy, automated archive
pruning, upload verification safety latch, and dry-run simulation in backup runner.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_ENGINE = REPO_ROOT / "tools" / "backup-runner" / "backup-engine.sh"
ENTRYPOINT = REPO_ROOT / "tools" / "backup-runner" / "entrypoint.sh"


class TestBackupRetentionPolicy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_backup_retention_")
        self.mock_bin = Path(self.temp_dir) / "bin"
        self.mock_bin.mkdir(parents=True, exist_ok=True)
        self.rclone_log = Path(self.temp_dir) / "rclone.log"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_rclone(self, behavior="success", candidate_count=2):
        """Creates an executable mock rclone script logging invocations."""
        mock_rclone = self.mock_bin / "rclone"
        content = f"""#!/usr/bin/env bash
echo "$*" >> "{self.rclone_log}"
cmd="$1"
case "${{cmd}}" in
  lsl)
"""
        if candidate_count > 0:
            content += """    echo "  10240 2026-08-01 12:00:00.000000000 actual-backup-2026-08-01_12-00-00.tar.gz.enc"
    echo "  20480 2026-08-10 12:00:00.000000000 actual-backup-2026-08-10_12-00-00.tar.gz.enc"
"""
        content += f"""    ;;
  copyto)
    if [[ "{behavior}" == "upload_fail" ]]; then
      echo "Upload connection failed" >&2
      exit 1
    fi
    exit 0
    ;;
  lsf)
    if [[ "{behavior}" == "verify_fail" ]]; then
      exit 0  # Empty output simulates missing remote file
    fi
    echo "remote_verified.enc"
    exit 0
    ;;
  delete|cleanup)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""
        mock_rclone.write_text(content)
        mock_rclone.chmod(0o755)
        return mock_rclone

    def test_scripts_exist_and_executable(self):
        self.assertTrue(BACKUP_ENGINE.exists(), f"{BACKUP_ENGINE} must exist")
        self.assertTrue(os.access(BACKUP_ENGINE, os.X_OK), f"{BACKUP_ENGINE} must be executable")
        self.assertTrue(ENTRYPOINT.exists(), f"{ENTRYPOINT} must exist")
        self.assertTrue(os.access(ENTRYPOINT, os.X_OK), f"{ENTRYPOINT} must be executable")

    def test_cli_help_documents_retention_and_dry_run(self):
        res = subprocess.run(
            [str(BACKUP_ENGINE), "--help"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--retention-days", res.stdout)
        self.assertIn("--dry-run", res.stdout)
        self.assertIn("--b2-dest-path", res.stdout)
        self.assertIn("--prune-only", res.stdout)

    def test_invalid_retention_days_rejected(self):
        invalid_values = ["0", "-1", "-30", "abc", "invalid"]
        for val in invalid_values:
            env = os.environ.copy()
            env["BACKUP_PASSPHRASE"] = "dummy_passphrase"
            env["BACKUP_RETENTION_DAYS"] = val
            res = subprocess.run(
                [str(BACKUP_ENGINE)],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(REPO_ROOT),
            )
            self.assertNotEqual(res.returncode, 0, f"Expected non-zero exit for BACKUP_RETENTION_DAYS={val}")
            self.assertIn("Invalid BACKUP_RETENTION_DAYS", res.stderr)

    def test_safety_latch_aborts_unverified_pruning(self):
        """prune_remote_backups() must strictly abort if BACKUP_UPLOAD_VERIFIED is not true."""
        env = os.environ.copy()
        env.pop("BACKUP_UPLOAD_VERIFIED", None)
        res = subprocess.run(
            [str(BACKUP_ENGINE), "--prune-only"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("SAFETY ABORT", res.stderr)
        self.assertIn("upload has not been verified", res.stderr)

    def test_safety_latch_allows_verified_pruning(self):
        """prune_remote_backups() executes when BACKUP_UPLOAD_VERIFIED=true."""
        self._create_mock_rclone()
        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["BACKUP_UPLOAD_VERIFIED"] = "true"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/actual"
        env["BACKUP_RETENTION_DAYS"] = "30"

        res = subprocess.run(
            [str(BACKUP_ENGINE), "--prune-only"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Initiating remote backup pruning", res.stdout)
        self.assertIn("Discovered 2 remote archive(s) eligible for pruning", res.stdout)
        self.assertIn("[PRUNED]", res.stdout)

        log_content = self.rclone_log.read_text()
        self.assertIn("lsl b2:test-bucket/backups/actual --min-age 30d", log_content)
        self.assertIn("delete b2:test-bucket/backups/actual --min-age 30d", log_content)
        self.assertIn("cleanup b2:test-bucket/backups/actual", log_content)

    def test_dry_run_simulation_flags(self):
        """When DRY_RUN=true, --dry-run is passed to rclone delete and cleanup."""
        self._create_mock_rclone()
        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["BACKUP_UPLOAD_VERIFIED"] = "true"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/actual"
        env["BACKUP_RETENTION_DAYS"] = "45"
        env["DRY_RUN"] = "true"

        res = subprocess.run(
            [str(BACKUP_ENGINE), "--prune-only"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("DRY_RUN is true", res.stdout)
        self.assertIn("Simulating deletion with --dry-run", res.stdout)

        log_content = self.rclone_log.read_text()
        self.assertIn("delete b2:test-bucket/backups/actual --min-age 45d --dry-run", log_content)
        self.assertIn("cleanup b2:test-bucket/backups/actual --dry-run", log_content)

    def test_cli_dry_run_flag(self):
        """--dry-run CLI flag overrides environment variable."""
        self._create_mock_rclone()
        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["BACKUP_UPLOAD_VERIFIED"] = "true"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/actual"
        env["BACKUP_RETENTION_DAYS"] = "60"
        env["DRY_RUN"] = "false"

        res = subprocess.run(
            [str(BACKUP_ENGINE), "--prune-only", "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("DRY_RUN is true", res.stdout)

        log_content = self.rclone_log.read_text()
        self.assertIn("delete b2:test-bucket/backups/actual --min-age 60d --dry-run", log_content)

    def test_no_candidates_logs_nothing_to_prune(self):
        """When rclone lsl returns no candidates, delete is skipped."""
        self._create_mock_rclone(candidate_count=0)
        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["BACKUP_UPLOAD_VERIFIED"] = "true"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/actual"

        res = subprocess.run(
            [str(BACKUP_ENGINE), "--prune-only"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Nothing to prune", res.stdout)

        log_content = self.rclone_log.read_text()
        self.assertNotIn("delete", log_content)
        self.assertIn("cleanup", log_content)

    def test_upload_failure_prevents_pruning_in_full_backup(self):
        """During a backup, if rclone upload fails, pruning is never called."""
        self._create_mock_rclone(behavior="upload_fail")
        src_dir = Path(self.temp_dir) / "src"
        src_dir.mkdir()
        (src_dir / "data.txt").write_text("sample")

        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["SERVICE_NAME"] = "test-service"
        env["BACKUP_MODE"] = "filesystem"
        env["BACKUP_SOURCE_DIR"] = str(src_dir)
        env["BACKUP_PASSPHRASE"] = "secret123"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/test-service"
        env["OUTPUT_DIR"] = str(Path(self.temp_dir) / "out")

        res = subprocess.run(
            [str(BACKUP_ENGINE)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)

        log_content = self.rclone_log.read_text() if self.rclone_log.exists() else ""
        self.assertNotIn("delete", log_content, "Pruning must NOT execute after upload failure")

    def test_upload_verification_failure_prevents_pruning(self):
        """During a backup, if upload verification fails (file missing on remote), pruning is never called."""
        self._create_mock_rclone(behavior="verify_fail")
        src_dir = Path(self.temp_dir) / "src"
        src_dir.mkdir()
        (src_dir / "data.txt").write_text("sample")

        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["SERVICE_NAME"] = "test-service"
        env["BACKUP_MODE"] = "filesystem"
        env["BACKUP_SOURCE_DIR"] = str(src_dir)
        env["BACKUP_PASSPHRASE"] = "secret123"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/test-service"
        env["OUTPUT_DIR"] = str(Path(self.temp_dir) / "out")

        res = subprocess.run(
            [str(BACKUP_ENGINE)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Upload verification failed", res.stderr)

        log_content = self.rclone_log.read_text() if self.rclone_log.exists() else ""
        self.assertNotIn("delete", log_content, "Pruning must NOT execute after upload verification failure")

    def test_successful_backup_triggers_upload_verification_and_pruning(self):
        """When backup creation and upload succeed, pruning runs with retention policy."""
        self._create_mock_rclone(behavior="success", candidate_count=1)
        src_dir = Path(self.temp_dir) / "src"
        src_dir.mkdir()
        (src_dir / "data.txt").write_text("sample")

        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}:{env.get('PATH', '')}"
        env["SERVICE_NAME"] = "test-service"
        env["BACKUP_MODE"] = "filesystem"
        env["BACKUP_SOURCE_DIR"] = str(src_dir)
        env["BACKUP_PASSPHRASE"] = "secret123"
        env["B2_DEST_PATH"] = "b2:test-bucket/backups/test-service"
        env["BACKUP_RETENTION_DAYS"] = "14"
        env["OUTPUT_DIR"] = str(Path(self.temp_dir) / "out")

        res = subprocess.run(
            [str(BACKUP_ENGINE)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Cloud upload verified successfully", res.stdout)
        self.assertIn("Initiating remote backup pruning (retention policy: 14 days)", res.stdout)

        log_content = self.rclone_log.read_text()
        self.assertIn("copyto", log_content)
        self.assertIn("lsf", log_content)
        self.assertIn("delete b2:test-bucket/backups/test-service --min-age 14d", log_content)
        self.assertIn("cleanup", log_content)

    def test_entrypoint_exports_retention_variables(self):
        """entrypoint.sh must export BACKUP_RETENTION_DAYS and DRY_RUN to /run/secrets/env_vars."""
        entrypoint_content = ENTRYPOINT.read_text()
        self.assertIn("BACKUP_RETENTION_DAYS", entrypoint_content)
        self.assertIn("DRY_RUN", entrypoint_content)
        self.assertIn("B2_DEST_PATH", entrypoint_content)


if __name__ == "__main__":
    unittest.main()
