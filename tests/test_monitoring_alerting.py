#!/usr/bin/env python3
"""
Unit tests validating Grafana unified alerting provisioning and Discord notification pipelines.
Validates that alert rules for disk exhaustion, memory starvation, container downtime,
and CPU saturation are declaratively provisioned with exact PromQL queries, thresholds,
durations, contact points, and notification policies.
"""

import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "monitoring" / "compose.yml"
ALERTING_FILE = REPO_ROOT / "monitoring" / "grafana" / "provisioning" / "alerting" / "alerting.yaml"


class TestMonitoringAlerting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(ALERTING_FILE.exists(), f"{ALERTING_FILE} does not exist")
        with open(ALERTING_FILE, "r", encoding="utf-8") as f:
            cls.alerting_text = f.read()
        cls.alerting_data = yaml.safe_load(cls.alerting_text)

        cls.assertTrue(COMPOSE_FILE.exists(), f"{COMPOSE_FILE} does not exist")
        with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
            cls.compose_text = f.read()
        cls.compose_data = yaml.safe_load(cls.compose_text)

    def test_alerting_file_exists_and_parses(self):
        """Verify alerting.yaml exists and adheres to apiVersion: 1 schema."""
        self.assertIsInstance(self.alerting_data, dict, "Alerting file must parse as a dictionary")
        self.assertEqual(self.alerting_data.get("apiVersion"), 1, "alerting.yaml must declare apiVersion: 1")
        self.assertIn("contactPoints", self.alerting_data, "alerting.yaml must declare 'contactPoints'")
        self.assertIn("policies", self.alerting_data, "alerting.yaml must declare 'policies'")
        self.assertIn("groups", self.alerting_data, "alerting.yaml must declare 'groups'")

    def test_contact_points_discord_configuration(self):
        """Verify Discord contact point receiver is configured with webhook settings and template."""
        contact_points = self.alerting_data.get("contactPoints", [])
        self.assertIsInstance(contact_points, list, "contactPoints must be a list")

        discord_cp = next((cp for cp in contact_points if cp.get("name") == "Discord-Alerts"), None)
        self.assertIsNotNone(discord_cp, "Must declare contactPoint named 'Discord-Alerts'")
        self.assertEqual(discord_cp.get("orgId"), 1)

        receivers = discord_cp.get("receivers", [])
        self.assertGreater(len(receivers), 0, "Discord-Alerts must define at least one receiver")

        discord_rcv = next((r for r in receivers if r.get("uid") == "discord-notifier"), None)
        self.assertIsNotNone(discord_rcv, "Receiver with uid 'discord-notifier' must exist")
        self.assertEqual(discord_rcv.get("type"), "discord")

        settings = discord_rcv.get("settings", {})
        self.assertIn("${DISCORD_WEBHOOK_URL}", settings.get("url", ""), "Receiver URL must interpolate DISCORD_WEBHOOK_URL")
        self.assertIn(".Annotations.summary", settings.get("message", ""), "Receiver message must format alert summary")
        self.assertIn(".Labels.severity", settings.get("message", ""), "Receiver message must format alert severity")

    def test_notification_policies_routing(self):
        """Verify notification policy tree routes alerts to Discord-Alerts with anti-flapping intervals."""
        policies = self.alerting_data.get("policies", [])
        self.assertIsInstance(policies, list, "policies must be a list")

        root_policy = next((p for p in policies if p.get("receiver") == "Discord-Alerts"), None)
        self.assertIsNotNone(root_policy, "Root policy must route to receiver 'Discord-Alerts'")
        self.assertEqual(root_policy.get("orgId"), 1)

        group_by = root_policy.get("group_by", [])
        self.assertIn("alertname", group_by)
        self.assertIn("service", group_by)

        self.assertEqual(root_policy.get("group_wait"), "30s")
        self.assertEqual(root_policy.get("group_interval"), "5m")
        self.assertEqual(root_policy.get("repeat_interval"), "4h")

    def test_alert_rule_groups_and_rules(self):
        """Verify the 5 required alert rules exist with exact UIDs, titles, severities, intervals, and PromQL expressions."""
        groups = self.alerting_data.get("groups", [])
        self.assertIsInstance(groups, list, "groups must be a list")

        infra_group = next((g for g in groups if g.get("name") == "Host-And-Container-Alerts"), None)
        self.assertIsNotNone(infra_group, "Group 'Host-And-Container-Alerts' must exist")
        self.assertEqual(infra_group.get("folder"), "Infrastructure-Alerts")
        self.assertEqual(infra_group.get("interval"), "1m")

        rules = infra_group.get("rules", [])
        self.assertEqual(len(rules), 5, f"Expected exactly 5 alert rules, found {len(rules)}")

        rule_map = {r.get("uid"): r for r in rules}

        expected_rules = {
            "alert-disk-warning": {
                "title": "Host Disk Exhaustion (Warning)",
                "for": "15m",
                "severity": "warning",
                "expr": '100 - ((node_filesystem_avail_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"} * 100) / node_filesystem_size_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"}) > 80',
            },
            "alert-disk-critical": {
                "title": "Host Disk Exhaustion (Critical)",
                "for": "5m",
                "severity": "critical",
                "expr": '100 - ((node_filesystem_avail_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"} * 100) / node_filesystem_size_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"}) > 90',
            },
            "alert-memory-starvation": {
                "title": "Host Memory Starvation",
                "for": "10m",
                "severity": "critical",
                "expr": '(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 < 10',
            },
            "alert-container-down": {
                "title": "Container Down or Crash Looping",
                "for": "2m",
                "severity": "critical",
                "expr": 'time() - container_last_seen{name=~"actual_server|vaultwarden|nginx-proxy-manager|homeassistant"} > 60',
            },
            "alert-cpu-saturation": {
                "title": "Sustained Host CPU Saturation",
                "for": "20m",
                "severity": "warning",
                "expr": '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 95',
            },
        }

        for uid, expected in expected_rules.items():
            self.assertIn(uid, rule_map, f"Missing required alert rule UID: {uid}")
            rule = rule_map[uid]
            self.assertEqual(rule.get("title"), expected["title"], f"Rule title mismatch for {uid}")
            self.assertEqual(rule.get("for"), expected["for"], f"Rule for-duration mismatch for {uid}")

            labels = rule.get("labels", {})
            self.assertEqual(labels.get("severity"), expected["severity"], f"Rule severity mismatch for {uid}")

            annotations = rule.get("annotations", {})
            self.assertTrue(bool(annotations.get("summary")), f"Rule {uid} missing summary annotation")
            self.assertTrue(bool(annotations.get("description")), f"Rule {uid} missing description annotation")

            # Validate PromQL query in data block
            data_blocks = rule.get("data", [])
            self.assertGreater(len(data_blocks), 0, f"Rule {uid} has no data blocks")
            query_block = next((d for d in data_blocks if d.get("refId") == "A"), data_blocks[0])
            self.assertEqual(query_block.get("datasourceUid"), "victoriametrics")
            expr = query_block.get("model", {}).get("expr", "")
            self.assertEqual(expr.strip(), expected["expr"].strip(), f"PromQL expression mismatch for {uid}")

    def test_compose_alerting_mount_and_environment(self):
        """Verify monitoring/compose.yml mounts alerting provisioning directory and sets DISCORD_WEBHOOK_URL."""
        services = self.compose_data.get("services", {})
        self.assertIn("grafana", services, "Grafana service must be defined in compose.yml")
        grafana = services["grafana"]

        # Alerting directory mount (must be read-only)
        volumes = grafana.get("volumes", [])
        expected_mount = "./grafana/provisioning/alerting:/etc/grafana/provisioning/alerting:ro"
        self.assertIn(expected_mount, volumes, f"Missing read-only alerting mount in Grafana: {volumes}")

        # DISCORD_WEBHOOK_URL environment variable
        env_vars = grafana.get("environment", [])
        self.assertTrue(
            any("DISCORD_WEBHOOK_URL" in env for env in env_vars),
            f"Grafana environment missing DISCORD_WEBHOOK_URL: {env_vars}"
        )

    def test_no_hardcoded_webhook_secrets(self):
        """Verify that no real Discord webhook URL tokens are hardcoded into Git."""
        forbidden_patterns = ["https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/"]
        for p in forbidden_patterns:
            self.assertNotIn(p, self.alerting_text, f"Hardcoded Discord webhook found in alerting.yaml: {p}")
            self.assertNotIn(p, self.compose_text, f"Hardcoded Discord webhook found in compose.yml: {p}")

    def test_docker_compose_config_validation(self):
        """Run docker compose config validation to ensure compose syntax remains valid."""
        res = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "config"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        self.assertEqual(
            res.returncode,
            0,
            f"docker compose config failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
