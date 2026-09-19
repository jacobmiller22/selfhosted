#!/usr/bin/env python3
"""
Unit tests validating migration of Actual Budget and Vaultwarden backup services
to the universal tools/backup-runner engine, and verifying elimination of duplicate scripts.
"""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestBackupRunnerMigration(unittest.TestCase):
    def setUp(self):
        self.actual_compose_path = REPO_ROOT / "actual" / "compose.yml"
        self.vw_compose_path = REPO_ROOT / "vaultwarden" / "compose.yml"

        self.assertTrue(self.actual_compose_path.exists(), "actual/compose.yml must exist")
        self.assertTrue(self.vw_compose_path.exists(), "vaultwarden/compose.yml must exist")

        with open(self.actual_compose_path, "r", encoding="utf-8") as f:
            self.actual_compose = yaml.safe_load(f)

        with open(self.vw_compose_path, "r", encoding="utf-8") as f:
            self.vw_compose = yaml.safe_load(f)

    def test_obsolete_actual_backup_files_eliminated(self):
        """Verify that legacy custom backup scripts in actual/backup/ are completely eliminated."""
        actual_backup_dir = REPO_ROOT / "actual" / "backup"
        self.assertFalse(
            (actual_backup_dir / "Dockerfile").exists(),
            "actual/backup/Dockerfile must be deleted",
        )
        self.assertFalse(
            (actual_backup_dir / "backup.sh").exists(),
            "actual/backup/backup.sh must be deleted",
        )
        self.assertFalse(
            (actual_backup_dir / "entrypoint.sh").exists(),
            "actual/backup/entrypoint.sh must be deleted",
        )
        self.assertFalse(
            actual_backup_dir.exists(),
            "actual/backup directory should no longer exist",
        )

    def test_obsolete_vaultwarden_backup_files_eliminated(self):
        """Verify that legacy custom backup scripts in vaultwarden/backup/ are completely eliminated."""
        vw_backup_dir = REPO_ROOT / "vaultwarden" / "backup"
        self.assertFalse(
            (vw_backup_dir / "Dockerfile").exists(),
            "vaultwarden/backup/Dockerfile must be deleted",
        )
        self.assertFalse(
            (vw_backup_dir / "backup.sh").exists(),
            "vaultwarden/backup/backup.sh must be deleted",
        )
        self.assertFalse(
            (vw_backup_dir / "entrypoint.sh").exists(),
            "vaultwarden/backup/entrypoint.sh must be deleted",
        )
        self.assertFalse(
            vw_backup_dir.exists(),
            "vaultwarden/backup directory should no longer exist",
        )

    def test_canonical_backup_runner_files_exist(self):
        """Verify the canonical shared backup runner engine files exist."""
        runner_dir = REPO_ROOT / "tools" / "backup-runner"
        self.assertTrue(runner_dir.exists(), "tools/backup-runner directory must exist")
        self.assertTrue((runner_dir / "Dockerfile").exists(), "tools/backup-runner/Dockerfile must exist")
        self.assertTrue((runner_dir / "backup-engine.sh").exists(), "tools/backup-runner/backup-engine.sh must exist")
        self.assertTrue((runner_dir / "entrypoint.sh").exists(), "tools/backup-runner/entrypoint.sh must exist")
        self.assertTrue((runner_dir / "test-backup-restore.sh").exists(), "tools/backup-runner/test-backup-restore.sh must exist")

    def _extract_env_map(self, env_list_or_dict):
        """Helper to normalize environment declarations into a dictionary."""
        if isinstance(env_list_or_dict, dict):
            return dict(env_list_or_dict)
        env_map = {}
        for item in env_list_or_dict:
            if "=" in item:
                k, v = item.split("=", 1)
                env_map[k] = v
            else:
                env_map[item] = ""
        return env_map

    def test_actual_backup_service_configuration(self):
        """Verify actual-backup service references tools/backup-runner with BACKUP_MODE=sqlite-auto."""
        services = self.actual_compose.get("services", {})
        self.assertIn("actual-backup", services, "actual-backup service must be declared")

        backup_svc = services["actual-backup"]
        build_cfg = backup_svc.get("build", {})
        if isinstance(build_cfg, str):
            build_context = build_cfg
        else:
            build_context = build_cfg.get("context", "")

        resolved_build_dir = (REPO_ROOT / "actual" / build_context).resolve()
        expected_runner_dir = (REPO_ROOT / "tools" / "backup-runner").resolve()
        self.assertEqual(
            resolved_build_dir,
            expected_runner_dir,
            f"actual-backup build context must resolve to {expected_runner_dir}, got {resolved_build_dir}",
        )

        env_map = self._extract_env_map(backup_svc.get("environment", []))
        self.assertEqual(env_map.get("SERVICE_NAME"), "actual")
        self.assertEqual(env_map.get("BACKUP_MODE"), "sqlite-auto")
        self.assertEqual(env_map.get("BACKUP_SOURCE_DIR"), "/tmp/actual-data")
        self.assertEqual(env_map.get("BACKUP_DEST_PREFIX"), "backups/actual")

        volumes = [str(v) for v in backup_svc.get("volumes", [])]
        self.assertTrue(
            any("actual-data:/tmp/actual-data:ro" in v for v in volumes),
            "actual-backup must mount actual-data:/tmp/actual-data:ro",
        )

    def test_vaultwarden_backup_service_configuration(self):
        """Verify vw-backup service references tools/backup-runner with BACKUP_MODE=sqlite-auto."""
        services = self.vw_compose.get("services", {})
        self.assertIn("vw-backup", services, "vw-backup service must be declared")

        backup_svc = services["vw-backup"]
        build_cfg = backup_svc.get("build", {})
        if isinstance(build_cfg, str):
            build_context = build_cfg
        else:
            build_context = build_cfg.get("context", "")

        resolved_build_dir = (REPO_ROOT / "vaultwarden" / build_context).resolve()
        expected_runner_dir = (REPO_ROOT / "tools" / "backup-runner").resolve()
        self.assertEqual(
            resolved_build_dir,
            expected_runner_dir,
            f"vw-backup build context must resolve to {expected_runner_dir}, got {resolved_build_dir}",
        )

        env_map = self._extract_env_map(backup_svc.get("environment", []))
        self.assertEqual(env_map.get("SERVICE_NAME"), "vaultwarden")
        self.assertEqual(env_map.get("BACKUP_MODE"), "sqlite-auto")
        self.assertEqual(env_map.get("BACKUP_SOURCE_DIR"), "/tmp/vw-data")
        self.assertEqual(env_map.get("BACKUP_DEST_PREFIX"), "backups/vaultwarden")

        volumes = [str(v) for v in backup_svc.get("volumes", [])]
        self.assertTrue(
            any("vw-data:/tmp/vw-data:ro" in v for v in volumes),
            "vw-backup must mount vw-data:/tmp/vw-data:ro",
        )

    def test_docker_compose_config_validation(self):
        """Verify that docker compose config parses both compose files cleanly."""
        if not shutil.which("docker"):
            self.skipTest("Docker binary not found on PATH")

        for name, compose_path in [
            ("Actual Budget", self.actual_compose_path),
            ("Vaultwarden", self.vw_compose_path),
        ]:
            res = subprocess.run(
                ["docker", "compose", "-f", str(compose_path), "config"],
                capture_output=True,
                text=True,
                cwd=str(compose_path.parent),
            )
            self.assertEqual(
                res.returncode,
                0,
                f"docker compose config failed for {name}:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}",
            )

    def test_backup_server_side_lifecycle_architecture(self):
        """Verify that backup-engine.sh relies on server-side B2 lifecycle rules rather than client-side deletion."""
        engine_script = REPO_ROOT / "tools" / "backup-runner" / "backup-engine.sh"
        content = engine_script.read_text(encoding="utf-8")
        # Ensure client-side deletion routines are eliminated from the engine
        self.assertNotIn("prune_remote_backups", content)
        self.assertNotIn("rclone delete", content)
        # Ensure upload verification remains active
        self.assertIn("Verifying cloud upload", content)
        self.assertIn("lifecycle", content.lower())


if __name__ == "__main__":
    unittest.main()

