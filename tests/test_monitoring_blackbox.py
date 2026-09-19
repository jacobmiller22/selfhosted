#!/usr/bin/env python3
"""
Unit tests validating Blackbox Exporter service deployment, configuration,
outside-in probe scrape targets in VictoriaMetrics, and alerting rules.
"""

import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "monitoring" / "compose.yml"
BLACKBOX_CONFIG_FILE = REPO_ROOT / "monitoring" / "blackbox" / "blackbox.yml"
PROMETHEUS_CONFIG_FILE = REPO_ROOT / "monitoring" / "victoriametrics" / "prometheus.yml"
ALERTING_FILE = REPO_ROOT / "monitoring" / "grafana" / "provisioning" / "alerting" / "alerting.yaml"


class TestMonitoringBlackbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(COMPOSE_FILE.exists(), f"{COMPOSE_FILE} does not exist")
        with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
            cls.compose_data = yaml.safe_load(f)

        cls.assertTrue(BLACKBOX_CONFIG_FILE.exists(), f"{BLACKBOX_CONFIG_FILE} does not exist")
        with open(BLACKBOX_CONFIG_FILE, "r", encoding="utf-8") as f:
            cls.blackbox_data = yaml.safe_load(f)

        cls.assertTrue(PROMETHEUS_CONFIG_FILE.exists(), f"{PROMETHEUS_CONFIG_FILE} does not exist")
        with open(PROMETHEUS_CONFIG_FILE, "r", encoding="utf-8") as f:
            cls.prom_data = yaml.safe_load(f)

        cls.assertTrue(ALERTING_FILE.exists(), f"{ALERTING_FILE} does not exist")
        with open(ALERTING_FILE, "r", encoding="utf-8") as f:
            cls.alerting_data = yaml.safe_load(f)

    def test_docker_compose_config_validation(self):
        """Run docker compose config validation to ensure compose syntax is strictly valid."""
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

    def test_blackbox_exporter_compose_service(self):
        """Verify blackbox-exporter service definition in compose.yml."""
        services = self.compose_data.get("services", {})
        self.assertIn("blackbox-exporter", services, "Service 'blackbox-exporter' must be in compose.yml")
        be = services["blackbox-exporter"]

        # Identity & Image
        self.assertTrue(
            be.get("image", "").startswith("prom/blackbox-exporter"),
            f"Image must be prom/blackbox-exporter, found: {be.get('image')}"
        )
        self.assertEqual(be.get("container_name"), "blackbox-exporter")
        self.assertEqual(be.get("restart"), "unless-stopped")

        # Network
        networks = be.get("networks", [])
        if isinstance(networks, dict):
            self.assertIn("monitoring", networks, "blackbox-exporter must be attached to 'monitoring' network")
        else:
            self.assertIn("monitoring", networks, "blackbox-exporter must be attached to 'monitoring' network")

        # Volume Mount (read-only config)
        volumes = be.get("volumes", [])
        self.assertTrue(
            any("./blackbox/blackbox.yml:/etc/blackbox_exporter/config.yml:ro" in str(v) for v in volumes),
            f"Must mount blackbox.yml to /etc/blackbox_exporter/config.yml:ro, found: {volumes}"
        )

        # Resource limits (mem_limit 64M, cpus 0.10)
        self.assertIn(str(be.get("mem_limit")).lower(), ["64m", "64mb"])
        self.assertIn(float(be.get("cpus")), [0.1, 0.10])

        deploy_limits = be.get("deploy", {}).get("resources", {}).get("limits", {})
        self.assertIn(str(deploy_limits.get("memory")).lower(), ["64m", "64mb"])
        self.assertIn(float(deploy_limits.get("cpus")), [0.1, 0.10])

    def test_blackbox_yaml_configuration(self):
        """Verify blackbox.yml declares http_2xx module with strict SSL/TLS enforcement."""
        self.assertIsInstance(self.blackbox_data, dict, "blackbox.yml must parse as a dictionary")
        modules = self.blackbox_data.get("modules", {})
        self.assertIn("http_2xx", modules, "blackbox.yml must define 'http_2xx' module")

        mod = modules["http_2xx"]
        self.assertEqual(mod.get("prober"), "http", "Prober type must be 'http'")
        self.assertEqual(mod.get("timeout"), "5s", "Timeout must be 5s")

        http_cfg = mod.get("http", {})
        self.assertEqual(http_cfg.get("valid_http_versions"), ["HTTP/1.1", "HTTP/2.0"])
        self.assertEqual(http_cfg.get("valid_status_codes"), [])
        self.assertEqual(http_cfg.get("method"), "GET")
        self.assertTrue(http_cfg.get("follow_redirects"))
        self.assertFalse(http_cfg.get("fail_if_ssl"))
        self.assertTrue(http_cfg.get("fail_if_not_ssl"))

        tls_cfg = http_cfg.get("tls_config", {})
        self.assertFalse(tls_cfg.get("insecure_skip_verify"))

    def test_prometheus_blackbox_scrape_job(self):
        """Verify VictoriaMetrics scrape_config has blackbox-http job targeting public FQDNs."""
        scrape_configs = self.prom_data.get("scrape_configs", [])
        job = next((j for j in scrape_configs if j.get("job_name") == "blackbox-http"), None)
        self.assertIsNotNone(job, "prometheus.yml must define 'blackbox-http' scrape job")

        self.assertEqual(job.get("metrics_path"), "/probe")
        self.assertEqual(job.get("params", {}).get("module"), ["http_2xx"])

        # Target verification
        targets = []
        for sc in job.get("static_configs", []):
            targets.extend(sc.get("targets", []))

        expected_targets = [
            "https://budget.cloud.jacobmiller22.com",
            "https://vw.cloud.jacobmiller22.com",
            "https://ha.cloud.jacobmiller22.com",
            "https://coolify.cloud.jacobmiller22.com",
            "https://monitoring.cloud.jacobmiller22.com",
        ]
        for expected in expected_targets:
            self.assertIn(expected, targets, f"Missing expected target: {expected}")

        # Relabel config verification
        relabel_configs = job.get("relabel_configs", [])
        self.assertGreaterEqual(len(relabel_configs), 3, "blackbox-http must have at least 3 relabel configs")

        # 1: __address__ -> __param_target
        rule1 = next((r for r in relabel_configs if r.get("target_label") == "__param_target"), None)
        self.assertIsNotNone(rule1, "Must have relabel rule targeting __param_target")
        self.assertEqual(rule1.get("source_labels"), ["__address__"])

        # 2: __param_target -> instance
        rule2 = next((r for r in relabel_configs if r.get("target_label") == "instance"), None)
        self.assertIsNotNone(rule2, "Must have relabel rule targeting instance")
        self.assertEqual(rule2.get("source_labels"), ["__param_target"])

        # 3: __address__ -> blackbox-exporter:9115
        rule3 = next((r for r in relabel_configs if r.get("target_label") == "__address__"), None)
        self.assertIsNotNone(rule3, "Must have relabel rule targeting __address__ replacement")
        self.assertEqual(rule3.get("replacement"), "blackbox-exporter:9115")

    def test_alerting_blackbox_rules(self):
        """Verify ServiceDown and SSLCertExpiringSoon alert definitions exist."""
        groups = self.alerting_data.get("groups", [])
        all_rules = []
        for g in groups:
            all_rules.extend(g.get("rules", []))

        rule_titles = {r.get("title"): r for r in all_rules}
        self.assertIn("ServiceDown", rule_titles, "ServiceDown alert rule must be defined")
        self.assertIn("SSLCertExpiringSoon", rule_titles, "SSLCertExpiringSoon alert rule must be defined")

        # ServiceDown validation
        sd_rule = rule_titles["ServiceDown"]
        self.assertEqual(sd_rule.get("labels", {}).get("severity"), "critical")
        sd_data = sd_rule.get("data", [])
        self.assertTrue(any("probe_success == 0" in d.get("model", {}).get("expr", "") for d in sd_data))

        # SSLCertExpiringSoon validation
        ssl_rule = rule_titles["SSLCertExpiringSoon"]
        self.assertEqual(ssl_rule.get("labels", {}).get("severity"), "warning")
        ssl_data = ssl_rule.get("data", [])
        self.assertTrue(
            any("probe_ssl_earliest_cert_expiry" in d.get("model", {}).get("expr", "") for d in ssl_data)
        )


if __name__ == "__main__":
    unittest.main()
