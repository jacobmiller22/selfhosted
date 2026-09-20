#!/usr/bin/env python3
"""
Unit tests validating Docker daemon and Compose log retention policies.
Ensures all repository Compose files enforce standardized log rotation limits
(driver: json-file, max-size: 10m, max-file: 3) to prevent unconstrained disk
consumption, and verifies host-level daemon.json documentation in INFRASTRUCTURE_TOPOLOGY.md.
"""

import shutil
import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

TARGET_COMPOSE_FILES = [
    REPO_ROOT / "actual" / "compose.yml",
    REPO_ROOT / "vaultwarden" / "compose.yml",
    REPO_ROOT / "monitoring" / "compose.yml",
    REPO_ROOT / "homeassistant" / "compose.yml",
    REPO_ROOT / "obsidian" / "compose.yml",
]


class TestInfraLoggingConfiguration(unittest.TestCase):
    def test_target_compose_files_exist_and_parse(self):
        """Verify all target compose files exist and parse cleanly as YAML dictionaries."""
        self.assertGreater(len(TARGET_COMPOSE_FILES), 0, "TARGET_COMPOSE_FILES must not be empty")
        for compose_file in TARGET_COMPOSE_FILES:
            self.assertTrue(compose_file.exists(), f"Compose file missing: {compose_file}")
            with open(compose_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIsInstance(
                data,
                dict,
                f"Compose file {compose_file.name} must parse to a dictionary, got {type(data)}",
            )
            self.assertIn(
                "services",
                data,
                f"Compose file {compose_file.name} must define a 'services' block",
            )

    def test_top_level_logging_anchor_defined(self):
        """Verify each target compose file defines the x-logging anchor with standard retention options."""
        for compose_file in TARGET_COMPOSE_FILES:
            with open(compose_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIn(
                "x-logging",
                data,
                f"Compose file {compose_file.relative_to(REPO_ROOT)} must define 'x-logging' anchor",
            )
            x_logging = data["x-logging"]
            self.assertEqual(
                x_logging.get("driver"),
                "json-file",
                f"x-logging in {compose_file.relative_to(REPO_ROOT)} must set driver 'json-file'",
            )
            opts = x_logging.get("options", {})
            self.assertEqual(
                opts.get("max-size"),
                "10m",
                f"x-logging in {compose_file.relative_to(REPO_ROOT)} must set max-size '10m'",
            )
            self.assertEqual(
                str(opts.get("max-file")),
                "3",
                f"x-logging in {compose_file.relative_to(REPO_ROOT)} must set max-file '3'",
            )

    def test_all_services_define_json_file_log_retention(self):
        """Verify that every service declared across target compose files enforces json-file log rotation."""
        for compose_file in TARGET_COMPOSE_FILES:
            with open(compose_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            services = data.get("services", {})
            self.assertGreater(
                len(services),
                0,
                f"Compose file {compose_file.relative_to(REPO_ROOT)} must define at least one service",
            )

            for svc_name, svc_cfg in services.items():
                self.assertIsNotNone(
                    svc_cfg,
                    f"Service '{svc_name}' in {compose_file.relative_to(REPO_ROOT)} cannot be empty",
                )
                self.assertIn(
                    "logging",
                    svc_cfg,
                    f"Service '{svc_name}' in {compose_file.relative_to(REPO_ROOT)} must define a 'logging' block",
                )
                logging_cfg = svc_cfg["logging"]
                self.assertEqual(
                    logging_cfg.get("driver"),
                    "json-file",
                    f"Service '{svc_name}' in {compose_file.relative_to(REPO_ROOT)} must use driver 'json-file'",
                )

                opts = logging_cfg.get("options", {})
                self.assertEqual(
                    opts.get("max-size"),
                    "10m",
                    f"Service '{svc_name}' in {compose_file.relative_to(REPO_ROOT)} must configure max-size '10m'",
                )
                self.assertEqual(
                    str(opts.get("max-file")),
                    "3",
                    f"Service '{svc_name}' in {compose_file.relative_to(REPO_ROOT)} must configure max-file '3'",
                )

    def test_docker_compose_config_validation(self):
        """Verify that docker compose config parses every target compose file cleanly without syntax errors."""
        if not shutil.which("docker"):
            self.skipTest("Docker binary not found on PATH")

        for compose_file in TARGET_COMPOSE_FILES:
            res = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "config"],
                capture_output=True,
                text=True,
                cwd=str(compose_file.parent),
            )
            self.assertEqual(
                res.returncode,
                0,
                f"docker compose config failed for {compose_file.relative_to(REPO_ROOT)}:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}",
            )

    def test_infrastructure_topology_documents_daemon_json(self):
        """Verify docs/INFRASTRUCTURE_TOPOLOGY.md documents /etc/docker/daemon.json for bjorn."""
        topology_file = REPO_ROOT / "docs" / "INFRASTRUCTURE_TOPOLOGY.md"
        self.assertTrue(topology_file.exists(), "docs/INFRASTRUCTURE_TOPOLOGY.md must exist")
        content = topology_file.read_text(encoding="utf-8")

        self.assertIn("/etc/docker/daemon.json", content)
        self.assertIn('"log-driver": "json-file"', content)
        self.assertIn('"max-size": "10m"', content)
        self.assertIn('"max-file": "3"', content)
        self.assertIn("bjorn", content)


if __name__ == "__main__":
    unittest.main()
