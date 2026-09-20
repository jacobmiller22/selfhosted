#!/usr/bin/env python3
"""
Unit tests validating frictionless universal backup runner enrollment for
Home Assistant, Nginx Proxy Manager, and Coolify pre-backup hook.
Verifies service definitions, build contexts, resource limits, read-only volume
mounts, environment parameters, and docker compose config validation.
"""

import os
import shutil
import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
HA_COMPOSE_PATH = REPO_ROOT / "homeassistant" / "compose.yml"
NPM_COMPOSE_PATH = REPO_ROOT / "nginx-proxy-manager" / "compose.yml"
COOLIFY_HOOK_PATH = REPO_ROOT / "tools" / "backup-runner" / "hooks" / "pre-backup-coolify.sh"
BACKUP_ARCH_DOC = REPO_ROOT / "docs" / "BACKUP_ARCHITECTURE.md"


class TestBackupRunnerEnrollment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(HA_COMPOSE_PATH.exists(), f"{HA_COMPOSE_PATH} must exist")
        cls.assertTrue(NPM_COMPOSE_PATH.exists(), f"{NPM_COMPOSE_PATH} must exist")

        with open(HA_COMPOSE_PATH, "r", encoding="utf-8") as f:
            cls.ha_compose = yaml.safe_load(f)

        with open(NPM_COMPOSE_PATH, "r", encoding="utf-8") as f:
            cls.npm_compose = yaml.safe_load(f)

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

    def test_compose_files_parse_as_valid_yaml(self):
        """Verify both compose files parse cleanly as valid YAML dictionaries."""
        self.assertIsInstance(self.ha_compose, dict, "homeassistant/compose.yml must parse as dict")
        self.assertIn("services", self.ha_compose, "homeassistant/compose.yml must contain 'services'")

        self.assertIsInstance(self.npm_compose, dict, "nginx-proxy-manager/compose.yml must parse as dict")
        self.assertIn("services", self.npm_compose, "nginx-proxy-manager/compose.yml must contain 'services'")

    def test_ha_backup_service_definition(self):
        """Verify ha-backup sidecar service configuration and resource caps."""
        services = self.ha_compose.get("services", {})
        self.assertIn("ha-backup", services, "ha-backup must be declared in homeassistant/compose.yml")
        svc = services["ha-backup"]

        # Build context resolution to tools/backup-runner
        build_cfg = svc.get("build", {})
        if isinstance(build_cfg, str):
            build_context = build_cfg
        else:
            build_context = build_cfg.get("context", "")

        resolved_build_dir = (REPO_ROOT / "homeassistant" / build_context).resolve()
        expected_runner_dir = (REPO_ROOT / "tools" / "backup-runner").resolve()
        self.assertEqual(
            resolved_build_dir,
            expected_runner_dir,
            f"ha-backup build context must resolve to {expected_runner_dir}, got: {resolved_build_dir}",
        )

        # Lifecycle & resource constraints
        self.assertEqual(svc.get("container_name"), "ha-backup")
        self.assertEqual(svc.get("restart"), "unless-stopped")
        mem_limit = str(svc.get("mem_limit", "")).lower()
        self.assertEqual(mem_limit, "256m", f"mem_limit must be 256m, got: {mem_limit}")
        self.assertIn(float(svc.get("cpus")), [0.5, 0.50], "cpus must be 0.50")

    def test_ha_backup_volume_mounts(self):
        """Verify ha-backup mounts ./config:/config:ro in strict read-only mode."""
        svc = self.ha_compose["services"]["ha-backup"]
        volumes = [str(v) for v in svc.get("volumes", [])]

        self.assertTrue(
            any("./config:/config:ro" in v for v in volumes),
            f"ha-backup must mount ./config:/config:ro, got: {volumes}",
        )
        for v in volumes:
            if "/config" in v:
                self.assertTrue(v.endswith(":ro"), f"Mount to /config must be read-only (:ro): {v}")

    def test_ha_backup_environment_variables(self):
        """Verify ha-backup environment configuration matches canonical specification."""
        svc = self.ha_compose["services"]["ha-backup"]
        env_map = self._extract_env_map(svc.get("environment", []))

        self.assertEqual(env_map.get("SERVICE_NAME"), "ha")
        self.assertEqual(env_map.get("BACKUP_MODE"), "sqlite-auto")
        self.assertEqual(env_map.get("BACKUP_SOURCE_DIR"), "/config")
        self.assertEqual(env_map.get("CRON_SCHEDULE"), "0 18 * * *")
        self.assertEqual(env_map.get("BACKUP_PASSPHRASE"), "${BACKUP_PASSPHRASE}")
        self.assertEqual(env_map.get("B2_APPLICATION_KEY_ID"), "${B2_APPLICATION_KEY_ID}")
        self.assertEqual(env_map.get("B2_APPLICATION_KEY"), "${B2_APPLICATION_KEY}")
        self.assertEqual(env_map.get("B2_BUCKET_NAME"), "${B2_BUCKET_NAME}")
        self.assertEqual(env_map.get("DISCORD_WEBHOOK_URL"), "${DISCORD_WEBHOOK_URL:-}")

    def test_npm_backup_service_definition(self):
        """Verify npm-backup sidecar service configuration and resource caps."""
        services = self.npm_compose.get("services", {})
        self.assertIn("npm-backup", services, "npm-backup must be declared in nginx-proxy-manager/compose.yml")
        svc = services["npm-backup"]

        # Build context resolution to tools/backup-runner
        build_cfg = svc.get("build", {})
        if isinstance(build_cfg, str):
            build_context = build_cfg
        else:
            build_context = build_cfg.get("context", "")

        resolved_build_dir = (REPO_ROOT / "nginx-proxy-manager" / build_context).resolve()
        expected_runner_dir = (REPO_ROOT / "tools" / "backup-runner").resolve()
        self.assertEqual(
            resolved_build_dir,
            expected_runner_dir,
            f"npm-backup build context must resolve to {expected_runner_dir}, got: {resolved_build_dir}",
        )

        # Lifecycle & resource constraints
        self.assertEqual(svc.get("container_name"), "npm-backup")
        self.assertEqual(svc.get("restart"), "unless-stopped")
        mem_limit = str(svc.get("mem_limit", "")).lower()
        self.assertEqual(mem_limit, "256m", f"mem_limit must be 256m, got: {mem_limit}")
        self.assertIn(float(svc.get("cpus")), [0.5, 0.50], "cpus must be 0.50")

        # Network attachment
        networks = svc.get("networks", [])
        self.assertIn("nginx-proxy-manager", networks, "npm-backup must attach to nginx-proxy-manager network")

    def test_npm_backup_volume_mounts(self):
        """Verify npm-backup mounts ./data and ./letsencrypt in strict read-only mode."""
        svc = self.npm_compose["services"]["npm-backup"]
        volumes = [str(v) for v in svc.get("volumes", [])]

        self.assertTrue(
            any("./data:/data:ro" in v for v in volumes),
            f"npm-backup must mount ./data:/data:ro, got: {volumes}",
        )
        self.assertTrue(
            any("./letsencrypt:/letsencrypt:ro" in v for v in volumes),
            f"npm-backup must mount ./letsencrypt:/letsencrypt:ro, got: {volumes}",
        )
        for v in volumes:
            self.assertTrue(v.endswith(":ro"), f"Mounts in npm-backup must be strictly read-only (:ro): {v}")

    def test_npm_backup_environment_variables(self):
        """Verify npm-backup environment configuration matches canonical specification."""
        svc = self.npm_compose["services"]["npm-backup"]
        env_map = self._extract_env_map(svc.get("environment", []))

        self.assertEqual(env_map.get("SERVICE_NAME"), "npm")
        self.assertEqual(env_map.get("BACKUP_MODE"), "sqlite-auto")
        self.assertEqual(env_map.get("BACKUP_SOURCE_DIR"), "/data")
        self.assertEqual(env_map.get("CRON_SCHEDULE"), "0 19 * * *")
        self.assertEqual(env_map.get("BACKUP_PASSPHRASE"), "${BACKUP_PASSPHRASE}")
        self.assertEqual(env_map.get("B2_APPLICATION_KEY_ID"), "${B2_APPLICATION_KEY_ID}")
        self.assertEqual(env_map.get("B2_APPLICATION_KEY"), "${B2_APPLICATION_KEY}")
        self.assertEqual(env_map.get("B2_BUCKET_NAME"), "${B2_BUCKET_NAME}")
        self.assertEqual(env_map.get("DISCORD_WEBHOOK_URL"), "${DISCORD_WEBHOOK_URL:-}")

    def test_coolify_pre_backup_hook(self):
        """Verify Coolify pre-backup hook script exists, is executable, and dumps PostgreSQL."""
        self.assertTrue(COOLIFY_HOOK_PATH.exists(), f"{COOLIFY_HOOK_PATH} must exist")
        self.assertTrue(
            os.access(COOLIFY_HOOK_PATH, os.X_OK),
            f"{COOLIFY_HOOK_PATH} must have executable permissions (+x)",
        )
        content = COOLIFY_HOOK_PATH.read_text(encoding="utf-8")
        self.assertIn("docker exec coolify-db pg_dump -U coolify -d coolify", content)
        self.assertIn("coolify.sql", content)

    def test_docker_compose_config_validation(self):
        """Verify docker compose config validates both stacks cleanly without errors."""
        if not shutil.which("docker"):
            self.skipTest("Docker CLI not available")

        for name, compose_path, expected_service in [
            ("Home Assistant", HA_COMPOSE_PATH, "ha-backup"),
            ("Nginx Proxy Manager", NPM_COMPOSE_PATH, "npm-backup"),
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
            self.assertIn(
                expected_service,
                res.stdout,
                f"Validated config for {name} must include service {expected_service}",
            )

    def test_backup_architecture_documentation(self):
        """Verify docs/BACKUP_ARCHITECTURE.md documents enrollment of HA and NPM."""
        self.assertTrue(BACKUP_ARCH_DOC.exists(), "docs/BACKUP_ARCHITECTURE.md must exist")
        content = BACKUP_ARCH_DOC.read_text(encoding="utf-8")

        self.assertIn("ha-backup", content, "BACKUP_ARCHITECTURE.md must mention ha-backup sidecar")
        self.assertIn("npm-backup", content, "BACKUP_ARCHITECTURE.md must mention npm-backup sidecar")
        self.assertIn("sqlite-auto", content, "BACKUP_ARCHITECTURE.md must document sqlite-auto mode")
        self.assertIn("pre-backup-coolify.sh", content, "BACKUP_ARCHITECTURE.md must document Coolify hook")


if __name__ == "__main__":
    unittest.main()
