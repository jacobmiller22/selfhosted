#!/usr/bin/env python3
"""
Unit tests validating monitoring/compose.yml telemetry exporters.
Validates that Node Exporter and unprivileged cAdvisor are correctly configured
with required read-only volume mounts, tuned performance flags, and strict resource limits.
"""

import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "monitoring" / "compose.yml"


class TestMonitoringCompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(COMPOSE_FILE.exists(), f"{COMPOSE_FILE} does not exist")
        with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
            cls.compose_text = f.read()
        cls.compose_data = yaml.safe_load(cls.compose_text)

    def test_compose_file_exists_and_parses(self):
        self.assertIsInstance(self.compose_data, dict, "Compose file must parse as a dictionary")
        self.assertIn("services", self.compose_data, "Compose file must declare 'services'")
        self.assertIn("networks", self.compose_data, "Compose file must declare 'networks'")

    def test_monitoring_network_declared(self):
        networks = self.compose_data.get("networks", {})
        self.assertIn("monitoring", networks, "The 'monitoring' network must be declared")
        self.assertEqual(networks["monitoring"].get("driver"), "bridge")

    def test_node_exporter_configuration(self):
        services = self.compose_data.get("services", {})
        self.assertIn("node-exporter", services, "'node-exporter' must be defined in services")
        ne = services["node-exporter"]

        # Image & Identity
        self.assertEqual(ne.get("image"), "quay.io/prometheus/node-exporter:v1.8.1")
        self.assertEqual(ne.get("container_name"), "node-exporter")
        self.assertEqual(ne.get("restart"), "unless-stopped")

        # Host Networking & PID Namespace
        self.assertEqual(ne.get("network_mode"), "host", "Node Exporter must run with network_mode: host")
        self.assertEqual(ne.get("pid"), "host", "Node Exporter must run with pid: host")

        # Volume Mounts: rootfs with ro,rslave
        volumes = ne.get("volumes", [])
        self.assertIn("/:/host:ro,rslave", volumes, "Node Exporter must mount /:/host:ro,rslave")
        for v in volumes:
            self.assertTrue(":ro" in v, f"All volume mounts for node-exporter must be read-only: {v}")

        # Command Flags
        commands = ne.get("command", [])
        cmd_str = " ".join(commands)
        self.assertIn("--path.rootfs=/host", cmd_str)
        self.assertIn("--collector.filesystem.mount-points-exclude=", cmd_str)
        self.assertIn("var/lib/docker", cmd_str)
        self.assertIn("--web.listen-address=:9100", cmd_str)

        # Resource Limits
        self.assertEqual(ne.get("mem_limit"), "30m")
        self.assertIn(float(ne.get("cpus")), [0.1, 0.10])

        deploy_limits = ne.get("deploy", {}).get("resources", {}).get("limits", {})
        self.assertEqual(deploy_limits.get("memory"), "30M")
        self.assertIn(float(deploy_limits.get("cpus")), [0.1, 0.10])

    def test_cadvisor_configuration(self):
        services = self.compose_data.get("services", {})
        self.assertIn("cadvisor", services, "'cadvisor' must be defined in services")
        cad = services["cadvisor"]

        # Image & Identity
        self.assertEqual(cad.get("image"), "gcr.io/cadvisor/cadvisor:v0.49.1")
        self.assertEqual(cad.get("container_name"), "cadvisor")
        self.assertEqual(cad.get("restart"), "unless-stopped")

        # Security: Privileged Mode MUST be False (Homelab Governance Axiom 4)
        self.assertFalse(
            cad.get("privileged", True),
            "cAdvisor MUST be unprivileged (privileged: false) per Axiom 4 single-server safety"
        )

        # Network & Ports
        networks = cad.get("networks", [])
        self.assertIn("monitoring", networks, "cAdvisor must be on 'monitoring' network")
        ports = cad.get("ports", [])
        self.assertTrue(
            any("8080:8080" in str(p) for p in ports),
            f"cAdvisor must expose port 8080:8080, found: {ports}"
        )

        # Volume Mounts: All read-only
        volumes = cad.get("volumes", [])
        expected_mounts = [
            "/:/rootfs:ro",
            "/var/run:/var/run:ro",
            "/sys:/sys:ro",
            "/var/lib/docker/:/var/lib/docker:ro",
            "/dev/disk/:/dev/disk:ro",
        ]
        for expected in expected_mounts:
            self.assertIn(expected, volumes, f"Missing expected mount: {expected}")
        for v in volumes:
            self.assertTrue(":ro" in v, f"All volume mounts for cadvisor must be read-only: {v}")

        # Command Tuning Flags
        commands = cad.get("command", [])
        cmd_str = " ".join(commands)
        self.assertIn("--housekeeping_interval=15s", cmd_str)
        self.assertIn("--disable_metrics=percpu,sched,process,hugetlb,referenced_memory", cmd_str)
        self.assertIn("--docker_only=true", cmd_str)

        # Resource Limits
        self.assertEqual(cad.get("mem_limit"), "80m")
        self.assertIn(float(cad.get("cpus")), [0.2, 0.20])

        deploy_limits = cad.get("deploy", {}).get("resources", {}).get("limits", {})
        self.assertEqual(deploy_limits.get("memory"), "80M")
        self.assertIn(float(deploy_limits.get("cpus")), [0.2, 0.20])

    def test_grafana_alerting_configuration(self):
        services = self.compose_data.get("services", {})
        self.assertIn("grafana", services, "'grafana' must be defined in services")
        grafana = services["grafana"]

        # Alerting provisioning volume mount
        volumes = grafana.get("volumes", [])
        self.assertIn(
            "./grafana/provisioning/alerting:/etc/grafana/provisioning/alerting:ro",
            volumes,
            "Grafana must mount alerting provisioning directory as read-only (:ro)"
        )

        # Discord Webhook Environment Variable
        env_vars = grafana.get("environment", [])
        self.assertTrue(
            any("DISCORD_WEBHOOK_URL" in e for e in env_vars),
            "Grafana must include DISCORD_WEBHOOK_URL in environment"
        )

    def test_no_hardcoded_secrets(self):
        forbidden_keys = ["BACKUP_PASSPHRASE=", "BACKUP_ENCRYPTION_KEY="]
        for key in forbidden_keys:
            self.assertNotIn(key, self.compose_text, f"Hardcoded secret detected: {key}")


if __name__ == "__main__":
    unittest.main()
