#!/usr/bin/env python3
"""
Unit tests validating obsidian/compose.yml and its universal backup runner enrollment.
Verifies Obsidian CouchDB LiveSync service definition, backup sidecar configuration,
read-only volume mounting, resource caps, environment parameters, and compose syntax.
"""

import shutil
import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATH = REPO_ROOT / "obsidian" / "compose.yml"


class TestObsidianCompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(COMPOSE_PATH.exists(), f"{COMPOSE_PATH} does not exist")
        with open(COMPOSE_PATH, "r", encoding="utf-8") as f:
            cls.compose_text = f.read()
        cls.compose_data = yaml.safe_load(cls.compose_text)

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

    def test_compose_file_exists_and_parses(self):
        """Verify compose file parses as a valid dictionary with services and networks."""
        self.assertIsInstance(self.compose_data, dict, "Compose file must parse as a dictionary")
        self.assertIn("services", self.compose_data, "Compose file must declare 'services'")
        self.assertIn("networks", self.compose_data, "Compose file must declare 'networks'")

    def test_couchdb_service_configuration(self):
        """Verify couchdb service declaration and attributes."""
        services = self.compose_data.get("services", {})
        self.assertIn("couchdb", services, "couchdb must be defined in services")
        cdb = services["couchdb"]

        self.assertEqual(cdb.get("container_name"), "livesync-db")
        self.assertEqual(cdb.get("image"), "couchdb:3.3.3")
        self.assertEqual(cdb.get("restart"), "unless-stopped")

        ports = [str(p) for p in cdb.get("ports", [])]
        self.assertTrue(any("5984:5984" in p for p in ports), f"Port 5984:5984 must be mapped, got: {ports}")

        volumes = [str(v) for v in cdb.get("volumes", [])]
        self.assertTrue(
            any("./db/data:/opt/couchdb/data" in v for v in volumes),
            f"Must mount ./db/data to /opt/couchdb/data, got: {volumes}",
        )

        networks = cdb.get("networks", [])
        self.assertIn("nginx-proxy-manager", networks, "couchdb must attach to nginx-proxy-manager network")

    def test_obsidian_backup_service_configuration(self):
        """Verify obsidian-backup sidecar service configuration."""
        services = self.compose_data.get("services", {})
        self.assertIn("obsidian-backup", services, "obsidian-backup service must be declared in services")
        backup_svc = services["obsidian-backup"]

        # Build context resolution to tools/backup-runner
        build_cfg = backup_svc.get("build", {})
        if isinstance(build_cfg, str):
            build_context = build_cfg
        else:
            build_context = build_cfg.get("context", "")

        resolved_build_dir = (REPO_ROOT / "obsidian" / build_context).resolve()
        expected_runner_dir = (REPO_ROOT / "tools" / "backup-runner").resolve()
        self.assertEqual(
            resolved_build_dir,
            expected_runner_dir,
            f"obsidian-backup build context must resolve to {expected_runner_dir}, got: {resolved_build_dir}",
        )
        self.assertTrue(expected_runner_dir.exists(), "tools/backup-runner directory must exist")

        # Identity & Lifecycle
        self.assertEqual(backup_svc.get("container_name"), "obsidian-backup")
        self.assertEqual(backup_svc.get("restart"), "unless-stopped")

        # Resource limits
        mem_limit = str(backup_svc.get("mem_limit", "")).lower()
        self.assertEqual(mem_limit, "256m", f"mem_limit must be 256M/256m, got: {mem_limit}")
        self.assertIn(float(backup_svc.get("cpus")), [0.5, 0.50], "cpus must be 0.50")

        # Volume Mount: must be read-only to eliminate lock contention
        volumes = [str(v) for v in backup_svc.get("volumes", [])]
        self.assertTrue(
            any("./db/data:/data:ro" in v for v in volumes),
            f"obsidian-backup must mount ./db/data:/data:ro in read-only mode, got: {volumes}",
        )
        for v in volumes:
            if "/data" in v:
                self.assertTrue(v.endswith(":ro"), f"Mount to /data must be strictly read-only (:ro): {v}")

        # Environment variables
        env_map = self._extract_env_map(backup_svc.get("environment", []))
        self.assertEqual(env_map.get("SERVICE_NAME"), "obsidian")
        self.assertEqual(env_map.get("BACKUP_MODE"), "filesystem")
        self.assertEqual(env_map.get("BACKUP_SOURCE_DIR"), "/data")
        self.assertEqual(env_map.get("CRON_SCHEDULE"), "0 17 * * *")
        self.assertEqual(env_map.get("B2_BUCKET"), "${B2_BUCKET}")
        self.assertEqual(env_map.get("B2_KEY_ID"), "${B2_KEY_ID}")
        self.assertEqual(env_map.get("B2_APPLICATION_KEY"), "${B2_APPLICATION_KEY}")
        self.assertEqual(env_map.get("BACKUP_PASSPHRASE"), "${BACKUP_PASSPHRASE}")
        self.assertEqual(env_map.get("DISCORD_WEBHOOK_URL"), "${DISCORD_WEBHOOK_URL:-}")

    def test_docker_compose_config_validation(self):
        """Verify that docker compose config parses obsidian/compose.yml cleanly."""
        if not shutil.which("docker"):
            self.skipTest("Docker binary not found on PATH")

        res = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_PATH), "config"],
            capture_output=True,
            text=True,
            cwd=str(COMPOSE_PATH.parent),
        )
        self.assertEqual(
            res.returncode,
            0,
            f"docker compose config failed for obsidian:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}",
        )
        self.assertIn("obsidian-backup:", res.stdout, "Validated compose config must contain obsidian-backup service")
        self.assertIn("couchdb:", res.stdout, "Validated compose config must contain couchdb service")

    def test_backup_documentation_references(self):
        """Verify disaster recovery and backup architecture docs cover Obsidian."""
        restore_doc = (REPO_ROOT / "docs" / "RESTORE.md").read_text(encoding="utf-8")
        self.assertIn("Obsidian CouchDB LiveSync", restore_doc, "RESTORE.md must document Obsidian CouchDB LiveSync")
        self.assertIn("livesync-db", restore_doc, "RESTORE.md must reference livesync-db container")
        self.assertIn("5984:5984", restore_doc, "RESTORE.md must document UID 5984 permissions quirk")

        arch_doc = (REPO_ROOT / "docs" / "BACKUP_ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("Obsidian LiveSync", arch_doc, "BACKUP_ARCHITECTURE.md must include Obsidian in inventory table")
        self.assertIn("filesystem", arch_doc, "BACKUP_ARCHITECTURE.md must describe filesystem backup mode")


if __name__ == "__main__":
    unittest.main()
