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
        self.assertEqual(env_map.get("GF_INSTALL_PLUGINS"), "frser-sqlite-datasource")

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
        self.assertTrue(
            any("actual-analytics-data:/var/lib/grafana/data/actual:ro" in str(v) for v in volumes),
            f"grafana must mount actual-analytics-data read-only, found: {volumes}"
        )

        # Top-level volume declaration
        top_volumes = self.compose_data.get("volumes", {})
        self.assertIn("grafana-data", top_volumes)
        self.assertIn("actual-analytics-data", top_volumes)

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
        self.assertTrue(datasources_file.exists(), f"{datasources_file} must exist")

        with open(datasources_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)
        datasources = data.get("datasources", [])
        self.assertTrue(len(datasources) > 0)

        vm_ds = next((ds for ds in datasources if ds.get("name") == "VictoriaMetrics"), None)
        self.assertIsNotNone(vm_ds, f"VictoriaMetrics datasource not found in {datasources_file}")
        self.assertEqual(vm_ds.get("type"), "prometheus")
        self.assertEqual(vm_ds.get("uid"), "victoriametrics")
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

    def test_actual_sqlite_datasource_provisioning(self):
        sqlite_ds_file = DATASOURCES_DIR / "actual-sqlite.yml"
        self.assertTrue(sqlite_ds_file.exists(), f"{sqlite_ds_file} must exist")
        with open(sqlite_ds_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)
        datasources = data.get("datasources", [])
        self.assertTrue(len(datasources) > 0)
        actual_ds = datasources[0]
        self.assertEqual(actual_ds.get("name"), "Actual Budget SQLite")
        self.assertEqual(actual_ds.get("uid"), "actual-sqlite")
        self.assertEqual(actual_ds.get("type"), "frser-sqlite-datasource")
        self.assertEqual(actual_ds.get("access"), "proxy")
        self.assertFalse(actual_ds.get("isDefault"))
        self.assertEqual(actual_ds.get("jsonData", {}).get("path"), "/var/lib/grafana/data/actual/db.sqlite")


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
        self.assertIn('node_filesystem_size_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"}', expr_blob)
        self.assertIn('node_filesystem_free_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"}', expr_blob)
        self.assertIn('100 - ((node_filesystem_avail_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"} * 100) / node_filesystem_size_bytes{mountpoint=~"/|/host",fstype!~"tmpfs|ramfs"})', expr_blob)

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


class TestActualBudgetAnalyticsDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard_file = DASHBOARDS_JSON_DIR / "actual-budget-analytics.json"
        cls.assertTrue(cls.dashboard_file.exists(), f"{cls.dashboard_file} must exist")
        with open(cls.dashboard_file, "r", encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_dashboard_metadata(self):
        self.assertEqual(self.data.get("uid"), "actual-budget-analytics")
        self.assertEqual(self.data.get("title"), "Actual Budget Analytics & Advanced Financial Intelligence")
        self.assertIn("sqlite", self.data.get("tags", []))
        self.assertIn("budget", self.data.get("tags", []))

    def test_all_six_sections_present(self):
        row_titles = [p.get("title") for p in self.data.get("panels", []) if p.get("type") == "row"]
        self.assertEqual(len(row_titles), 6, f"Expected 6 section rows, found: {row_titles}")
        expected_sections = [
            "Executive Financial Health",
            "Cash Flow Dynamics",
            "Statistical Anomaly",
            "Merchant & Payee Intelligence",
            "Predictive Forecasting",
            "Hierarchical Category Decomposition"
        ]
        for expected in expected_sections:
            self.assertTrue(
                any(expected.lower() in r.lower() for r in row_titles),
                f"Missing expected section: {expected} in {row_titles}"
            )

    def test_plain_english_descriptions_on_all_visual_panels(self):
        panels = self.data.get("panels", [])
        visual_panels = [p for p in panels if p.get("type") not in ("row", "text")]
        self.assertTrue(len(visual_panels) >= 12, f"Expected at least 12 visual panels, found {len(visual_panels)}")
        for p in visual_panels:
            desc = p.get("description", "")
            self.assertTrue(len(desc) > 20, f"Panel '{p.get('title')}' is missing a detailed description")
            self.assertIn("Plain English", desc, f"Panel '{p.get('title')}' must contain 'Plain English' in tooltip")

    def test_markdown_guidance_cards_present(self):
        text_panels = [p for p in self.data.get("panels", []) if p.get("type") == "text"]
        self.assertEqual(len(text_panels), 6, f"Expected 6 guidance markdown panels (1 per section), found {len(text_panels)}")
        for tp in text_panels:
            content = tp.get("options", {}).get("content", "")
            self.assertIn("How to Read", content, f"Guidance panel '{tp.get('title')}' should explain how to read the metrics")

    def test_templating_variables(self):
        templating = self.data.get("templating", {}).get("list", [])
        var_names = [v.get("name") for v in templating]
        self.assertIn("account", var_names, "Dashboard must have 'account' template variable")
        self.assertIn("category_group", var_names, "Dashboard must have 'category_group' template variable")

    def test_sqlite_target_schema_compatibility(self):
        panels = self.data.get("panels", [])
        visual_panels = [p for p in panels if p.get("type") not in ("row", "text")]
        checked = 0
        for p in visual_panels:
            targets = p.get("targets", [])
            self.assertTrue(len(targets) > 0, f"Panel '{p.get('title')}' must have at least one target")
            for t in targets:
                self.assertIn("rawQueryText", t, f"Panel '{p.get('title')}' missing rawQueryText required by frser-sqlite-datasource")
                self.assertIn("queryText", t, f"Panel '{p.get('title')}' missing queryText required by frser-sqlite-datasource")
                self.assertTrue(len(t["rawQueryText"]) > 0, f"Panel '{p.get('title')}' rawQueryText cannot be empty")
                self.assertEqual(t["rawQueryText"], t["queryText"])
                checked += 1
        self.assertTrue(checked >= 15, f"Expected at least 15 queries checked, got {checked}")

    def test_timeseries_panel_configuration(self):
        panels = {p.get("id"): p for p in self.data.get("panels", [])}
        panel_202 = panels.get(202)
        self.assertIsNotNone(panel_202, "Panel 202 must exist")
        self.assertEqual(panel_202.get("type"), "timeseries")
        targets = panel_202.get("targets", [])
        self.assertTrue(len(targets) > 0)
        target = targets[0]
        self.assertIn("timeColumns", target, "Timeseries panel must define timeColumns for frser-sqlite-datasource")
        self.assertIn("time", target["timeColumns"], "timeColumns must contain 'time'")
        self.assertIn("AS time", target["rawQueryText"], "Query must alias timestamp column as 'time'")

    def test_multi_row_panel_reduce_options(self):
        panels = {p.get("id"): p for p in self.data.get("panels", [])}
        panel_105 = panels.get(105)
        self.assertIsNotNone(panel_105, "Panel 105 (piechart) must exist")
        self.assertEqual(panel_105.get("type"), "piechart")
        self.assertTrue(panel_105.get("options", {}).get("reduceOptions", {}).get("values"),
                        "Panel 105 piechart must have reduceOptions.values = true to render multi-row slices")

        panel_107 = panels.get(107)
        self.assertIsNotNone(panel_107, "Panel 107 (Asset Allocation piechart) must exist")
        self.assertEqual(panel_107.get("type"), "piechart")
        self.assertTrue(panel_107.get("options", {}).get("reduceOptions", {}).get("values"),
                        "Panel 107 piechart must have reduceOptions.values = true to render asset class slices")

        panel_303 = panels.get(303)
        self.assertIsNotNone(panel_303, "Panel 303 (bargauge) must exist")
        self.assertEqual(panel_303.get("type"), "bargauge")
        self.assertTrue(panel_303.get("options", {}).get("reduceOptions", {}).get("values"),
                        "Panel 303 bargauge must have reduceOptions.values = true to render category bars")

    def test_sqlite_queries_execute_cleanly(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        cur = con.cursor()

        # Seed mock schema matching Actual Budget db.sqlite
        cur.executescript("""
            CREATE TABLE accounts (
                id TEXT PRIMARY KEY,
                name TEXT,
                closed INTEGER DEFAULT 0,
                offbudget INTEGER DEFAULT 0,
                tombstone INTEGER DEFAULT 0
            );
            CREATE TABLE category_groups (
                id TEXT PRIMARY KEY,
                name TEXT,
                is_income INTEGER DEFAULT 0,
                tombstone INTEGER DEFAULT 0
            );
            CREATE TABLE categories (
                id TEXT PRIMARY KEY,
                name TEXT,
                cat_group TEXT,
                is_income INTEGER DEFAULT 0,
                tombstone INTEGER DEFAULT 0
            );
            CREATE TABLE payees (
                id TEXT PRIMARY KEY,
                name TEXT,
                transfer_acct TEXT,
                tombstone INTEGER DEFAULT 0
            );
            CREATE TABLE transactions (
                id TEXT PRIMARY KEY,
                isParent INTEGER DEFAULT 0,
                isChild INTEGER DEFAULT 0,
                date INTEGER,
                amount INTEGER,
                acct TEXT,
                category TEXT,
                description TEXT,
                imported_description TEXT,
                transferred_id TEXT,
                tombstone INTEGER DEFAULT 0
            );
            CREATE TABLE zero_budgets (
                id TEXT,
                month INTEGER,
                category TEXT,
                amount INTEGER
            );

            INSERT INTO accounts (id, name, closed, offbudget, tombstone) VALUES
                ('acc1', '360 Checking', 0, 0, 0),
                ('acc2', '360 Savings', 0, 0, 0);
            INSERT INTO category_groups (id, name, is_income, tombstone) VALUES
                ('cg1', 'Expected', 0, 0),
                ('cg2', 'Fun', 0, 0),
                ('cg3', 'Income', 1, 0);
            INSERT INTO categories (id, name, cat_group, is_income, tombstone) VALUES
                ('c1', 'Groceries', 'cg1', 0, 0),
                ('c2', 'Dining Out', 'cg2', 0, 0),
                ('c3', 'Paycheck', 'cg3', 1, 0);
            INSERT INTO payees (id, name, tombstone) VALUES
                ('p1', 'Trader Joe', 0),
                ('p2', 'Netflix', 0);
            INSERT INTO zero_budgets (id, month, category, amount) VALUES
                ('zb1', 202609, 'c1', 50000),
                ('zb2', 202609, 'c2', 30000);
            INSERT INTO transactions (id, date, amount, acct, category, description, imported_description, tombstone) VALUES
                ('t1', 20260905, -7500, 'acc1', 'c1', 'p1', 'Trader Joe', 0),
                ('t2', 20260910, -1500, 'acc1', 'c2', 'p2', 'Netflix', 0),
                ('t3', 20260915, 300000, 'acc1', 'c3', NULL, 'Employer', 0);
        """)

        panels = self.data.get("panels", [])
        executed_queries = 0
        for p in panels:
            for target in p.get("targets", []):
                raw_sql = target.get("rawQueryText") or target.get("rawSql")
                if raw_sql:
                    # Grafana frontend expands template variables before passing SQL to SQLite.
                    # Simulate default '$__all' expansion:
                    clean_sql = (
                        raw_sql.replace("${category_group:singlequote}", "'$__all'")
                        .replace("${account:singlequote}", "'$__all'")
                    )
                    try:
                        cur.execute(clean_sql)
                        executed_queries += 1
                    except Exception as e:
                        self.fail(f"Query in panel '{p.get('title')}' failed with error: {e}\nSQL:\n{clean_sql}")

        self.assertTrue(executed_queries >= 12, f"Expected at least 12 SQL queries executed, got {executed_queries}")


if __name__ == "__main__":
    unittest.main()
