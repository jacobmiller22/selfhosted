#!/usr/bin/env python3
"""
Unit tests validating Grafana service configuration, provisioning files,
and declarative dashboard JSON schemas for host and container telemetry.
"""

import json
import subprocess
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "monitoring" / "compose.yml"
DATASOURCES_DIR = REPO_ROOT / "monitoring" / "grafana" / "provisioning" / "datasources"
DASHBOARDS_DIR = REPO_ROOT / "monitoring" / "grafana" / "provisioning" / "dashboards"
DASHBOARDS_JSON_DIR = REPO_ROOT / "monitoring" / "grafana" / "dashboards"


class TestGrafanaCompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(COMPOSE_FILE.exists(), f"{COMPOSE_FILE} does not exist")
        with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
            cls.compose_text = f.read()
        cls.compose_data = yaml.safe_load(cls.compose_text)

    def test_compose_file_exists_and_parses(self):
        self.assertIsInstance(self.compose_data, dict, "Compose file must parse as a dictionary")
        self.assertIn("services", self.compose_data)
        self.assertIn("networks", self.compose_data)
        self.assertIn("volumes", self.compose_data)

    def test_grafana_service_definition(self):
        services = self.compose_data.get("services", {})
        self.assertIn("grafana", services, "'grafana' service must be defined in compose.yml")
        grafana = services["grafana"]

        # Image & Identity
        self.assertEqual(grafana.get("image"), "grafana/grafana:11.2.0")
        self.assertEqual(grafana.get("container_name"), "grafana")
        self.assertEqual(grafana.get("restart"), "unless-stopped")

    def test_grafana_resource_limits(self):
        services = self.compose_data.get("services", {})
        grafana = services.get("grafana", {})

        # Strict resource bounds
        self.assertEqual(grafana.get("mem_limit"), "120m")
        self.assertEqual(float(grafana.get("cpus")), 0.25)

        deploy_res = grafana.get("deploy", {}).get("resources", {})
        limits = deploy_res.get("limits", {})
        self.assertEqual(limits.get("memory"), "120M")
        self.assertEqual(float(limits.get("cpus")), 0.25)

        reservations = deploy_res.get("reservations", {})
        self.assertEqual(reservations.get("memory"), "60M")

    def test_grafana_environment_variables(self):
        services = self.compose_data.get("services", {})
        grafana = services.get("grafana", {})
        env = grafana.get("environment", [])

        # Normalize env list or dict
        if isinstance(env, list):
            env_map = {}
            for item in env:
                k, v = item.split("=", 1)
                env_map[k] = v
        else:
            env_map = env

        self.assertIn("GF_SECURITY_ADMIN_USER", env_map)
        self.assertIn("GF_SECURITY_ADMIN_PASSWORD", env_map)
        self.assertEqual(env_map.get("GF_USERS_ALLOW_SIGN_UP"), "false")
        self.assertIn("GF_SERVER_ROOT_URL", env_map)
        self.assertIn("https://monitoring.cloud.jacobmiller22.com", env_map["GF_SERVER_ROOT_URL"])
        self.assertEqual(env_map.get("GF_SERVER_SERVE_FROM_SUB_PATH"), "false")
        self.assertEqual(env_map.get("GF_ANALYTICS_REPORTING_ENABLED"), "false")
        self.assertEqual(env_map.get("GF_ANALYTICS_CHECK_FOR_UPDATES"), "false")
        self.assertEqual(env_map.get("GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES"), "false")

    def test_grafana_volume_mounts_and_declarations(self):
        services = self.compose_data.get("services", {})
        grafana = services.get("grafana", {})
        volumes = grafana.get("volumes", [])

        # Required volume mounts
        self.assertTrue(
            any("grafana-data:/var/lib/grafana" in str(v) for v in volumes),
            f"grafana must mount grafana-data:/var/lib/grafana, found: {volumes}"
        )
        self.assertTrue(
            any("./grafana/provisioning/datasources:/etc/grafana/provisioning/datasources:ro" in str(v) for v in volumes),
            f"grafana must mount datasources provisioning read-only, found: {volumes}"
        )
        self.assertTrue(
            any("./grafana/provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro" in str(v) for v in volumes),
            f"grafana must mount dashboards provisioning read-only, found: {volumes}"
        )
        self.assertTrue(
            any("./grafana/dashboards:/var/lib/grafana/dashboards:ro" in str(v) for v in volumes),
            f"grafana must mount dashboards folder read-only, found: {volumes}"
        )

        # Top-level volume declaration
        top_volumes = self.compose_data.get("volumes", {})
        self.assertIn("grafana-data", top_volumes)

    def test_grafana_networks(self):
        services = self.compose_data.get("services", {})
        grafana = services.get("grafana", {})
        networks = grafana.get("networks", [])
        self.assertIn("monitoring", networks, "grafana must join 'monitoring' network")
        self.assertIn("nginx-proxy-manager", networks, "grafana must join 'nginx-proxy-manager' network")

    def test_grafana_healthcheck(self):
        services = self.compose_data.get("services", {})
        grafana = services.get("grafana", {})
        healthcheck = grafana.get("healthcheck", {})
        self.assertIsNotNone(healthcheck)
        test_cmd = healthcheck.get("test", [])
        test_cmd_str = " ".join(test_cmd) if isinstance(test_cmd, list) else str(test_cmd)
        self.assertIn("http://127.0.0.1:3000/api/health", test_cmd_str)

    def test_docker_compose_config_validation(self):
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


class TestGrafanaProvisioning(unittest.TestCase):
    def test_datasource_provisioning_files(self):
        datasources_file = DATASOURCES_DIR / "datasources.yml"
        vm_file = DATASOURCES_DIR / "victoriametrics.yml"

        self.assertTrue(datasources_file.exists(), f"{datasources_file} must exist")
        self.assertTrue(vm_file.exists(), f"{vm_file} must exist")

        for file_path in [datasources_file, vm_file]:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIsInstance(data, dict)
            datasources = data.get("datasources", [])
            self.assertTrue(len(datasources) > 0)

            vm_ds = next((ds for ds in datasources if ds.get("name") == "VictoriaMetrics"), None)
            self.assertIsNotNone(vm_ds, f"VictoriaMetrics datasource not found in {file_path}")
            self.assertEqual(vm_ds.get("type"), "prometheus")
            self.assertEqual(vm_ds.get("access"), "proxy")
            self.assertEqual(vm_ds.get("url"), "http://victoria-metrics:8428")
            self.assertTrue(vm_ds.get("isDefault"))
            json_data = vm_ds.get("jsonData", {})
            self.assertEqual(json_data.get("httpMethod"), "POST")
            self.assertEqual(json_data.get("timeInterval"), "15s")

    def test_dashboard_provider_configuration(self):
        dashboards_file = DASHBOARDS_DIR / "dashboards.yml"
        self.assertTrue(dashboards_file.exists(), f"{dashboards_file} must exist")
        with open(dashboards_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        providers = data.get("providers", [])
        self.assertTrue(len(providers) > 0)
        provider = providers[0]
        self.assertEqual(provider.get("type"), "file")
        options = provider.get("options", {})
        self.assertEqual(options.get("path"), "/var/lib/grafana/dashboards")


class TestGrafanaDashboards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host_file = DASHBOARDS_JSON_DIR / "host-metrics.json"
        container_file = DASHBOARDS_JSON_DIR / "container-metrics.json"

        cls.assertTrue(host_file.exists(), f"{host_file} must exist")
        cls.assertTrue(container_file.exists(), f"{container_file} must exist")

        with open(host_file, "r", encoding="utf-8") as f:
            cls.host_data = json.load(f)
        with open(container_file, "r", encoding="utf-8") as f:
            cls.container_data = json.load(f)

    def test_host_metrics_dashboard(self):
        self.assertEqual(self.host_data.get("uid"), "host-overview")
        self.assertEqual(self.host_data.get("title"), "Host Overview & Capacity (bjorn)")

        # Collect all query expressions across panels
        exprs = []
        for panel in self.host_data.get("panels", []):
            for target in panel.get("targets", []):
                if "expr" in target:
                    exprs.append(target["expr"])

        expr_blob = " ".join(exprs)

        # Storage
        self.assertIn("node_filesystem_size_bytes{mountpoint=\"/host\"}", expr_blob)
        self.assertIn("node_filesystem_free_bytes{mountpoint=\"/host\"}", expr_blob)
        self.assertIn("100 - ((node_filesystem_avail_bytes{mountpoint=\"/host\"} * 100) / node_filesystem_size_bytes{mountpoint=\"/host\"})", expr_blob)

        # Memory & Swap
        self.assertIn("node_memory_MemTotal_bytes", expr_blob)
        self.assertIn("node_memory_MemAvailable_bytes", expr_blob)
        self.assertIn("node_memory_SwapTotal_bytes", expr_blob)
        self.assertIn("node_memory_SwapFree_bytes", expr_blob)

        # CPU & Load
        self.assertIn('100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)', expr_blob)
        self.assertIn("node_load1", expr_blob)
        self.assertIn("node_load5", expr_blob)
        self.assertIn("node_load15", expr_blob)

        # Network
        self.assertIn('rate(node_network_receive_bytes_total{device!~"lo|docker.*|veth.*|br-.*"}[5m])', expr_blob)
        self.assertIn('rate(node_network_transmit_bytes_total{device!~"lo|docker.*|veth.*|br-.*"}[5m])', expr_blob)

    def test_container_metrics_dashboard(self):
        self.assertEqual(self.container_data.get("uid"), "container-telemetry")
        self.assertEqual(self.container_data.get("title"), "Container Telemetry & Resource Attribution")

        # Verify templating variable
        variables = self.container_data.get("templating", {}).get("list", [])
        self.assertTrue(len(variables) > 0, "Dashboard must declare template variables")
        var = variables[0]
        self.assertTrue(var.get("includeAll"), "Variable must support 'All' option")
        query = var.get("query", {})
        query_str = query.get("query", "") if isinstance(query, dict) else str(query)
        self.assertIn("label_values(container_cpu_usage_seconds_total, name)", query_str)

        # Collect all query expressions across panels
        exprs = []
        for panel in self.container_data.get("panels", []):
            for target in panel.get("targets", []):
                if "expr" in target:
                    exprs.append(target["expr"])

        expr_blob = " ".join(exprs)

        # Top CPU
        self.assertIn('topk(10, sum(rate(container_cpu_usage_seconds_total{name!="",image!=""}[5m])) by (name) * 100)', expr_blob)

        # Top Memory
        self.assertIn('topk(10, sum(container_memory_working_set_bytes{name!="",image!=""}) by (name))', expr_blob)

        # Network
        self.assertIn('sum(rate(container_network_receive_bytes_total{name!="",image!=""}[5m])) by (name)', expr_blob)
        self.assertIn('sum(rate(container_network_transmit_bytes_total{name!="",image!=""}[5m])) by (name)', expr_blob)

        # Disk I/O
        self.assertIn('sum(rate(container_fs_reads_bytes_total{name!="",image!=""}[5m])) by (name)', expr_blob)
        self.assertIn('sum(rate(container_fs_writes_bytes_total{name!="",image!=""}[5m])) by (name)', expr_blob)


if __name__ == "__main__":
    unittest.main()
