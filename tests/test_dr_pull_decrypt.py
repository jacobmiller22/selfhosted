#!/usr/bin/env python3
"""
Unit tests validating Disaster Recovery (DR) Pull & Decrypt Engine.
Verifies CLI help, argument parsing, OpenSSL Salted__ magic header validation,
local archive discovery, and decryption lifecycle.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "backup-dr" / "pull-and-decrypt.sh"
TEST_SUITE_PATH = REPO_ROOT / "tools" / "backup-dr" / "test-dr-pull-decrypt.sh"


class TestDRPullDecryptScript(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_dr_py_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scripts_exist_and_are_executable(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"{SCRIPT_PATH} must exist")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), f"{SCRIPT_PATH} must be executable")

        self.assertTrue(TEST_SUITE_PATH.exists(), f"{TEST_SUITE_PATH} must exist")
        self.assertTrue(os.access(TEST_SUITE_PATH, os.X_OK), f"{TEST_SUITE_PATH} must be executable")

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
            self.assertIn("--file", res.stdout)
            self.assertIn("--dest", res.stdout)
            self.assertIn("--passphrase", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--keep", res.stdout)
            self.assertIn("BACKUP_PASSPHRASE", res.stdout)
            self.assertIn("BACKUP_ENCRYPTION_KEY", res.stdout)

    def test_cli_argument_validation(self):
        # Invalid option
        res = subprocess.run(
            [str(SCRIPT_PATH), "--nonexistent-option"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unknown option", res.stderr)

        # Missing value for flag
        res = subprocess.run(
            [str(SCRIPT_PATH), "--service"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Missing value", res.stderr)

        # Unsupported source
        res = subprocess.run(
            [str(SCRIPT_PATH), "--source", "invalid_source"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unsupported source", res.stderr)

        # File source without file
        res = subprocess.run(
            [str(SCRIPT_PATH), "--source", "file"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("--file <path> is required", res.stderr)

        # Nonexistent file
        nonexistent = Path(self.temp_dir) / "missing.enc"
        res = subprocess.run(
            [str(SCRIPT_PATH), "--file", str(nonexistent)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("does not exist", res.stderr)

    def _create_openssl_archive(self, payload_dir: Path, out_path: Path, passphrase: str):
        tar_cmd = ["tar", "-cz", "-C", str(payload_dir), "."]
        tar_proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE)
        env = os.environ.copy()
        env["ENC_PASS"] = passphrase
        enc_cmd = [
            "openssl", "enc", "-aes-256-cbc", "-md", "sha256",
            "-pbkdf2", "-iter", "100000", "-salt",
            "-pass", "env:ENC_PASS",
            "-out", str(out_path)
        ]
        enc_proc = subprocess.Popen(enc_cmd, stdin=tar_proc.stdout, env=env)
        if tar_proc.stdout:
            tar_proc.stdout.close()
        enc_proc.communicate()
        tar_proc.wait()
        self.assertEqual(enc_proc.returncode, 0)
        self.assertEqual(tar_proc.returncode, 0)

    def test_magic_header_validation(self):
        # 1. Valid archive
        src = Path(self.temp_dir) / "src_valid"
        src.mkdir()
        (src / "test.txt").write_text("hello world", encoding="utf-8")
        valid_archive = Path(self.temp_dir) / "valid.tar.gz.enc"
        self._create_openssl_archive(src, valid_archive, "testpass")

        res_valid = subprocess.run(
            [str(SCRIPT_PATH), "--file", str(valid_archive), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_valid.returncode, 0)
        self.assertIn("Salted__", res_valid.stdout)

        # 2. Corrupted header
        corrupt_archive = Path(self.temp_dir) / "corrupt.tar.gz.enc"
        corrupt_archive.write_bytes(b"INVALID_HEADER_DATA_1234567890")

        res_corrupt = subprocess.run(
            [str(SCRIPT_PATH), "--file", str(corrupt_archive), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res_corrupt.returncode, 0)
        self.assertIn("Salted__", res_corrupt.stderr)

        # 3. Truncated archive (<16 bytes)
        truncated_archive = Path(self.temp_dir) / "truncated.tar.gz.enc"
        truncated_archive.write_bytes(b"Salted")

        res_trunc = subprocess.run(
            [str(SCRIPT_PATH), "--file", str(truncated_archive), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res_trunc.returncode, 0)
        self.assertIn("truncated or too small", res_corrupt.stderr + res_trunc.stderr)

    def test_local_discovery_chronological_selection(self):
        backup_dir = Path(self.temp_dir) / "backups"
        backup_dir.mkdir()
        src = Path(self.temp_dir) / "src_disc"
        src.mkdir()
        (src / "sample.txt").write_text("discovery data", encoding="utf-8")

        # Create archives with chronological timestamps
        t1 = backup_dir / "actual-backup-2026-09-17_10-00-00.tar.gz.enc"
        t2 = backup_dir / "actual-backup-2026-09-18_18-00-00.tar.gz.enc"  # Newest
        t3 = backup_dir / "actual-backup-2026-09-18_12-00-00.tar.gz.enc"
        t_other = backup_dir / "vaultwarden-backup-2026-09-18_20-00-00.tar.gz.enc"

        for p in [t1, t2, t3, t_other]:
            self._create_openssl_archive(src, p, "dummy-key")

        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--service", "actual",
                "--source", "local",
                "--backup-dir", str(backup_dir),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("actual-backup-2026-09-18_18-00-00.tar.gz.enc", res.stdout)
        self.assertNotIn("vaultwarden", res.stdout)

    def test_decryption_roundtrip_and_passphrase_resolution(self):
        src = Path(self.temp_dir) / "roundtrip_src"
        src.mkdir()
        (src / "manifest.json").write_text('{"service": "actual", "v": 1}', encoding="utf-8")
        archive = Path(self.temp_dir) / "roundtrip.tar.gz.enc"
        self._create_openssl_archive(src, archive, "CorrectPass123!")

        dest_a = Path(self.temp_dir) / "extract_a"
        dest_a.mkdir()

        # 1. Via CLI --passphrase
        res = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--file", str(archive),
                "--passphrase", "CorrectPass123!",
                "--dest", str(dest_a),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Decryption failed: {res.stderr}")
        self.assertTrue((dest_a / "manifest.json").exists())
        self.assertEqual((dest_a / "manifest.json").read_text(encoding="utf-8"), '{"service": "actual", "v": 1}')

        # 2. Invalid passphrase rejection
        dest_fail = Path(self.temp_dir) / "extract_fail"
        dest_fail.mkdir()
        res_fail = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--file", str(archive),
                "--passphrase", "WrongPass123!",
                "--dest", str(dest_fail),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertNotEqual(res_fail.returncode, 0)

        # 3. Via BACKUP_ENCRYPTION_KEY fallback
        dest_b = Path(self.temp_dir) / "extract_b"
        dest_b.mkdir()
        env = os.environ.copy()
        env.pop("BACKUP_PASSPHRASE", None)
        env["BACKUP_ENCRYPTION_KEY"] = "CorrectPass123!"

        res_b = subprocess.run(
            [
                str(SCRIPT_PATH),
                "--file", str(archive),
                "--dest", str(dest_b),
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res_b.returncode, 0, f"Fallback failed: {res_b.stderr}")
        self.assertTrue((dest_b / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
