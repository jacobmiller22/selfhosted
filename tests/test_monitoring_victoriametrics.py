#!/usr/bin/env python3
"""
Unit tests validating VictoriaMetrics service deployment and scrape configurations.
Validates that VictoriaMetrics is defined with lightweight TSDB parameters,
correct volume mounts, resource caps, and scrape relabel configurations.
"""

import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "monitoring" / "compose.yml"
PROMETHEUS_CONFIG_FILE = REPO_ROOT / "monitoring" / "victoriametrics" / "prometheus.yml"


class TestMonitoringVictoriaMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(COMPOSE_FILE.exists(), f"{COMPOSE_FILE} does not exist")
        with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
            cls.compose_text = f.read()
        cls.compose_data = yaml.safe_load(cls.compose_text)

        cls.assertTrue(PROMETHEUS_CONFIG_FILE.exists(), f"{PROMETHEUS_CONFIG_FILE} does not exist")
        with open(PROMETHEUS_CONFIG_FILE, "r", encoding="utf-8") as f:
            cls.prom_text = f.read()
        cls.prom_data = yaml.safe_load(cls.prom_text)

    def test_compose_file_exists_and_parses(self):
        """Verify monitoring/compose.yml exists and parses cleanly."""
        self.assertIsInstance(self.compose_data, dict, "Compose file must parse as a dictionary")
        self.assertIn("services", self.compose_data, "Compose file must declare 'services'")
        self.assertIn("networks", self.compose_data, "Compose file must declare 'networks'")
        self.assertIn("volumes", self.compose_data, "Compose file must declare 'volumes'")

    def test_victoria_metrics_service_definition(self):
        """Verify victoria-metrics service identity, image, and network."""
        services = self.compose_data.get("services", {})
        self.assertIn("victoria-metrics", services, "'victoria-metrics' service must be declared in compose.yml")
        vm = services["victoria-metrics"]

        # Image & Identity
        self.assertEqual(vm.get("image"), "victoriametrics/victoria-metrics:v1.99.0")
        self.assertEqual(vm.get("container_name"), "victoria-metrics")
        self.assertEqual(vm.get("restart"), "unless-stopped")

        # Network
        networks = vm.get("networks", [])
        if isinstance(networks, dict):
            self.assertIn("monitoring", networks, "victoria-metrics must be attached to 'monitoring' network")
        else:
            self.assertIn("monitoring", networks, "victoria-metrics must be attached to 'monitoring' network")

    def test_victoria_metrics_extra_hosts(self):
        """Verify extra_hosts maps node-exporter to host-gateway for host network scraping."""
        services = self.compose_data.get("services", {})
        vm = services.get("victoria-metrics", {})
        extra_hosts = vm.get("extra_hosts", [])
        self.assertIn("node-exporter:host-gateway", extra_hosts)

    def test_victoria_metrics_volume_mounts_and_declarations(self):
        """Verify volume mounts for TSDB persistence and read-only prometheus config."""
        services = self.compose_data.get("services", {})
        vm = services.get("victoria-metrics", {})
        volumes = vm.get("volumes", [])

        # Persistent TSDB volume mount
        self.assertTrue(
            any("victoria-data:/victoria-metrics-data" in str(v) for v in volumes),
            f"victoria-metrics must mount victoria-data:/victoria-metrics-data, found: {volumes}"
        )

        # Prometheus configuration mount (must be read-only)
        prom_mounts = [v for v in volumes if "prometheus.yml" in str(v)]
        self.assertTrue(len(prom_mounts) > 0, "victoria-metrics must mount prometheus.yml")
        for pm in prom_mounts:
            self.assertTrue(
                str(pm).endswith(":ro"),
                f"prometheus.yml mount must be read-only (:ro), found: {pm}"
            )

        # Top-level volume declaration
        top_volumes = self.compose_data.get("volumes", {})
        self.assertIn(
            "victoria-data",
            top_volumes,
            "Top-level 'volumes' section must declare 'victoria-data'"
        )

    def test_victoria_metrics_command_flags(self):
        """Verify command arguments for retention, storage path, scrape config, and query duration."""
        services = self.compose_data.get("services", {})
        vm = services.get("victoria-metrics", {})
        commands = vm.get("command", [])
        cmd_str = " ".join(commands)

        self.assertIn("-promscrape.config=/etc/prometheus/prometheus.yml", cmd_str)
        self.assertIn("-promscrape.config.strictParse=false", cmd_str)
        self.assertIn("-storageDataPath=/victoria-metrics-data", cmd_str)
        self.assertIn("-retentionPeriod=90d", cmd_str)
        self.assertIn("-search.maxQueryDuration=30s", cmd_str)
        self.assertIn("-maxLabelsPerTimeseries=64", cmd_str)

    def test_victoria_metrics_ports(self):
        """Verify port 8428 is exposed."""
        services = self.compose_data.get("services", {})
        vm = services.get("victoria-metrics", {})
        ports = [str(p) for p in vm.get("ports", [])]
        self.assertTrue(
            any("8428:8428" in p for p in ports),
            f"Port 8428:8428 must be exposed, found: {ports}"
        )

    def test_victoria_metrics_resource_limits(self):
        """Verify memory and CPU bounds (mem_limit: 128m, cpus: 0.25)."""
        services = self.compose_data.get("services", {})
        vm = services.get("victoria-metrics", {})

        self.assertEqual(vm.get("mem_limit"), "128m")
        self.assertIn(float(vm.get("cpus")), [0.25])

        deploy_limits = vm.get("deploy", {}).get("resources", {}).get("limits", {})
        self.assertEqual(deploy_limits.get("memory"), "128M")
        self.assertIn(float(deploy_limits.get("cpus")), [0.25])

    def test_prometheus_scrape_config_validity(self):
        """Verify prometheus.yml scrape interval and jobs."""
        self.assertIsInstance(self.prom_data, dict, "prometheus.yml must parse as a dictionary")
        global_cfg = self.prom_data.get("global", {})
        self.assertIn(global_cfg.get("scrape_interval"), ["15s", "30s"])
        self.assertNotIn(
            "evaluation_interval",
            global_cfg,
            "VictoriaMetrics promscrape strictly rejects evaluation_interval in Prometheus global config"
        )

        scrape_configs = self.prom_data.get("scrape_configs", [])
        job_map = {job.get("job_name"): job for job in scrape_configs}

        # Verify 'node' job targets node-exporter:9100
        self.assertIn("node", job_map, "Scrape config must define job 'node'")
        node_targets = []
        for sc in job_map["node"].get("static_configs", []):
            node_targets.extend(sc.get("targets", []))
        self.assertIn("node-exporter:9100", node_targets, "'node' job must target node-exporter:9100")

        # Verify 'cadvisor' job targets cadvisor:8080
        self.assertIn("cadvisor", job_map, "Scrape config must define job 'cadvisor'")
        cad_targets = []
        for sc in job_map["cadvisor"].get("static_configs", []):
            cad_targets.extend(sc.get("targets", []))
        self.assertIn("cadvisor:8080", cad_targets, "'cadvisor' job must target cadvisor:8080")

    def test_cadvisor_metric_relabel_configs(self):
        """Verify cadvisor job normalizes container labels (container_label_com_docker_compose_service -> service)."""
        scrape_configs = self.prom_data.get("scrape_configs", [])
        cad_job = next((j for j in scrape_configs if j.get("job_name") == "cadvisor"), None)
        self.assertIsNotNone(cad_job, "'cadvisor' job must be present")

        relabel_configs = cad_job.get("metric_relabel_configs", [])
        self.assertTrue(len(relabel_configs) > 0, "cadvisor job must define metric_relabel_configs")

        service_relabel = next(
            (r for r in relabel_configs if r.get("target_label") == "service"),
            None
        )
        self.assertIsNotNone(
            service_relabel,
            "metric_relabel_configs must contain rule for target_label 'service'"
        )
        source_labels = service_relabel.get("source_labels", [])
        self.assertIn(
            "container_label_com_docker_compose_service",
            source_labels,
            "Service relabel rule must use source label 'container_label_com_docker_compose_service'"
        )
        self.assertEqual(service_relabel.get("action", "replace"), "replace")

    def test_docker_compose_config_validation(self):
        """Run docker compose config validation to ensure syntax is valid."""
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
