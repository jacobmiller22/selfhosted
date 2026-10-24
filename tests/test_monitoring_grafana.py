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
        self.assertTrue(
            any("btcupdown-data:/var/lib/grafana/data/btcupdown:ro" in str(v) for v in volumes),
            f"grafana must mount btcupdown-data read-only, found: {volumes}"
        )

        # Top-level volume declaration
        top_volumes = self.compose_data.get("volumes", {})
        self.assertIn("grafana-data", top_volumes)
        self.assertIn("actual-analytics-data", top_volumes)
        self.assertIn("btcupdown-data", top_volumes)

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
        self.assertTrue(options.get("foldersFromFilesStructure", False))

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

    def test_btcupdown_sqlite_datasource_provisioning(self):
        sqlite_ds_file = DATASOURCES_DIR / "btcupdown-sqlite.yml"
        self.assertTrue(sqlite_ds_file.exists(), f"{sqlite_ds_file} must exist")
        with open(sqlite_ds_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertIsInstance(data, dict)
        datasources = data.get("datasources", [])
        self.assertTrue(len(datasources) > 0)
        btc_ds = datasources[0]
        self.assertEqual(btc_ds.get("name"), "SQLite (btcupdown)")
        self.assertEqual(btc_ds.get("uid"), "btcupdown-sqlite")
        self.assertEqual(btc_ds.get("type"), "frser-sqlite-datasource")
        self.assertEqual(btc_ds.get("access"), "proxy")
        self.assertFalse(btc_ds.get("isDefault"))
        self.assertEqual(btc_ds.get("jsonData", {}).get("path"), "/var/lib/grafana/data/btcupdown/broker.sqlite")


class TestGrafanaDashboards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host_file = next(DASHBOARDS_JSON_DIR.rglob("host-metrics.json"))
        container_file = next(DASHBOARDS_JSON_DIR.rglob("container-metrics.json"))
        dr_file = next(DASHBOARDS_JSON_DIR.rglob("dr-and-backups.json"))

        cls.assertTrue(host_file.exists(), f"{host_file} must exist")
        cls.assertTrue(container_file.exists(), f"{container_file} must exist")
        cls.assertTrue(dr_file.exists(), f"{dr_file} must exist")

        with open(host_file, "r", encoding="utf-8") as f:
            cls.host_data = json.load(f)
        with open(container_file, "r", encoding="utf-8") as f:
            cls.container_data = json.load(f)
        with open(dr_file, "r", encoding="utf-8") as f:
            cls.dr_data = json.load(f)

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

    def test_dr_and_backups_dashboard(self):
        self.assertEqual(self.dr_data.get("uid"), "dr-and-backups")
        self.assertIn("Disaster Recovery", self.dr_data.get("title", ""))

        # Collect query expressions
        exprs = []
        for panel in self.dr_data.get("panels", []):
            for target in panel.get("targets", []):
                if "expr" in target:
                    exprs.append(target["expr"])
        expr_blob = " ".join(exprs)

        # DR & backup metrics
        self.assertIn("selfhosted_backup_last_timestamp_seconds", expr_blob)
        self.assertIn("selfhosted_backup_size_bytes", expr_blob)
        self.assertIn("selfhosted_backup_status", expr_blob)
        self.assertIn("selfhosted_dr_drill_rto_seconds", expr_blob)
        self.assertIn("selfhosted_dr_drill_rpo_seconds", expr_blob)
        self.assertIn("selfhosted_dr_drill_status", expr_blob)

        # Validate ELI5 descriptions on visual panels
        visual_panels = [p for p in self.dr_data.get("panels", []) if p.get("type") not in ("row", "text")]
        for p in visual_panels:
            desc = p.get("description", "")
            self.assertIn("What is RTO?", desc)
            self.assertIn("What is RPO?", desc)
            self.assertIn("What should I do if this is red?", desc)


class TestActualBudgetAnalyticsDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard_file = next(DASHBOARDS_JSON_DIR.rglob("actual-budget-analytics.json"))
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

        panel_103 = panels.get(103)
        self.assertIsNotNone(panel_103, "Panel 103 (runway gauge) must exist")
        self.assertEqual(panel_103.get("type"), "gauge")
        unit_103 = panel_103.get("fieldConfig", {}).get("defaults", {}).get("unit")
        self.assertEqual(unit_103, "suffix: mo",
                         f"Panel 103 unit must be 'suffix: mo' to avoid Grafana interpreting 'm' as minutes, got '{unit_103}'")

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
                    try:
                        cur.execute(raw_sql)
                        executed_queries += 1
                    except Exception as e:
                        self.fail(f"Query in panel '{p.get('title')}' failed with error: {e}\nSQL:\n{raw_sql}")

        self.assertTrue(executed_queries >= 12, f"Expected at least 12 SQL queries executed, got {executed_queries}")


class TestBTCUpDownDashboards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboards_dir = DASHBOARDS_JSON_DIR / "btcupdown"
        cls.d1_file = cls.dashboards_dir / "01-strategy-leaderboards.json"
        cls.d2_file = cls.dashboards_dir / "02-experiments-monitor.json"
        cls.d3_file = cls.dashboards_dir / "03-market-signals-and-trades.json"

        cls.assertTrue(cls.d1_file.exists(), f"{cls.d1_file} must exist")
        cls.assertTrue(cls.d2_file.exists(), f"{cls.d2_file} must exist")
        cls.assertTrue(cls.d3_file.exists(), f"{cls.d3_file} must exist")

        with open(cls.d1_file, "r", encoding="utf-8") as f:
            cls.d1 = json.load(f)
        with open(cls.d2_file, "r", encoding="utf-8") as f:
            cls.d2 = json.load(f)
        with open(cls.d3_file, "r", encoding="utf-8") as f:
            cls.d3 = json.load(f)

    def test_dashboards_metadata_and_uids(self):
        self.assertEqual(self.d1.get("uid"), "btcupdown-strategy-leaderboards")
        self.assertEqual(self.d2.get("uid"), "btcupdown-experiments-monitor")
        self.assertEqual(self.d3.get("uid"), "btcupdown-market-signals-and-trades")

        for d in [self.d1, self.d2, self.d3]:
            self.assertIn("btcupdown", d.get("tags", []))

    def test_all_sqlite_queries_execute_cleanly_against_broker_schema(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        cur = con.cursor()

        # Seed schema matching crates/data-broker/src/store.rs
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS strategy_experiments (
                participant_id       TEXT NOT NULL,
                experiment_id        TEXT NOT NULL,
                generator_id         TEXT,
                status               TEXT NOT NULL,
                start_balance        REAL NOT NULL,
                strategies_json      TEXT NOT NULL,
                params_override_json TEXT,
                started_at_ms        INTEGER NOT NULL,
                end_at_ms            INTEGER,
                max_cycles           INTEGER,
                cycles_observed      INTEGER NOT NULL DEFAULT 0,
                drain_deadline_ms    INTEGER,
                completed_at_ms      INTEGER,
                force_closed         INTEGER NOT NULL DEFAULT 0,
                updated_at_ms        INTEGER NOT NULL,
                ingested_at_ms       INTEGER NOT NULL,
                PRIMARY KEY (participant_id, experiment_id)
            );

            CREATE TABLE IF NOT EXISTS strategy_standings (
                participant_id       TEXT NOT NULL,
                experiment_id        TEXT NOT NULL,
                strategy_id          TEXT NOT NULL,
                display_label        TEXT NOT NULL,
                cash_dollars         REAL NOT NULL,
                trades               INTEGER NOT NULL,
                wins                 INTEGER NOT NULL,
                losses               INTEGER NOT NULL,
                win_rate_pct         REAL NOT NULL,
                realized_pnl_dollars REAL NOT NULL,
                watching_json        TEXT,
                settling_json        TEXT NOT NULL,
                updated_at_ms        INTEGER NOT NULL,
                ingested_at_ms       INTEGER NOT NULL,
                PRIMARY KEY (participant_id, experiment_id, strategy_id)
            );

            CREATE TABLE IF NOT EXISTS strategy_trades (
                participant_id       TEXT NOT NULL,
                experiment_id        TEXT NOT NULL,
                trade_id             INTEGER NOT NULL,
                strategy_id          TEXT NOT NULL,
                cycle_id             TEXT NOT NULL,
                ticker               TEXT NOT NULL,
                side                 TEXT NOT NULL,
                contracts            INTEGER NOT NULL,
                entry_price          REAL NOT NULL,
                cost                 REAL NOT NULL,
                status               TEXT NOT NULL,
                exit_reason          TEXT,
                exit_price           REAL,
                pnl                  REAL,
                won                  INTEGER,
                opened_at_ms         INTEGER NOT NULL,
                closed_at_ms         INTEGER,
                ingested_at_ms       INTEGER NOT NULL,
                PRIMARY KEY (participant_id, experiment_id, trade_id)
            );

            CREATE TABLE IF NOT EXISTS strategy_outputs (
                participant_id       TEXT NOT NULL,
                experiment_id        TEXT NOT NULL,
                output_id            INTEGER NOT NULL,
                strategy_id          TEXT NOT NULL,
                cycle_key            TEXT NOT NULL,
                ts_ms                INTEGER NOT NULL,
                output_kind          TEXT NOT NULL,
                log_line             TEXT NOT NULL,
                payload_json         TEXT NOT NULL,
                ingested_at_ms       INTEGER NOT NULL,
                PRIMARY KEY (participant_id, experiment_id, output_id)
            );

            CREATE TABLE IF NOT EXISTS cycles (
                cycle_key            TEXT PRIMARY KEY,
                producer_id          TEXT NOT NULL,
                topic                TEXT NOT NULL,
                contract_id          TEXT,
                first_seen_ms        INTEGER NOT NULL,
                last_seen_ms         INTEGER NOT NULL,
                open_strike          REAL,
                latest_spot          REAL,
                current_state        TEXT,
                locked_direction     TEXT,
                locked_confidence    REAL,
                locked_reversal_risk REAL,
                price_at_lock        REAL,
                latest_price_now     REAL,
                locked_at_ms         INTEGER,
                tick_count           INTEGER NOT NULL DEFAULT 0,
                state_change_count   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS raw_events (
                event_id             INTEGER PRIMARY KEY,
                producer_id          TEXT NOT NULL,
                topic                TEXT NOT NULL,
                cycle_key            TEXT,
                contract_id          TEXT,
                observed_at_ms       INTEGER NOT NULL,
                ingested_at_ms       INTEGER NOT NULL,
                is_state_change      INTEGER NOT NULL,
                normalized_json      TEXT NOT NULL,
                extra_json           TEXT NOT NULL,
                changed_fields_json  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS state_changes (
                event_id             INTEGER PRIMARY KEY,
                producer_id          TEXT NOT NULL,
                topic                TEXT NOT NULL,
                cycle_key            TEXT,
                contract_id          TEXT,
                observed_at_ms       INTEGER NOT NULL,
                ingested_at_ms       INTEGER NOT NULL,
                is_state_change      INTEGER NOT NULL,
                normalized_json      TEXT NOT NULL,
                extra_json           TEXT NOT NULL,
                changed_fields_json  TEXT NOT NULL
            );
        """)

        total_queries = 0
        import re

        for dashboard in [self.d1, self.d2, self.d3]:
            # 1. Audit template variables
            for var in dashboard.get("templating", {}).get("list", []):
                v_type = var.get("type")
                v_query = var.get("query")
                if v_type == "query" and isinstance(v_query, str) and v_query.strip():
                    total_queries += 1
                    sub_sql = (
                        v_query.replace("$participant", "alice")
                        .replace("$experiment", "exp-1")
                        .replace("$strategy", "all")
                    )
                    try:
                        cur.execute(sub_sql)
                    except Exception as e:
                        self.fail(f"Template variable query failed: {sub_sql}\nError: {e}")

            # 2. Audit panel targets
            for p in dashboard.get("panels", []):
                for target in p.get("targets", []):
                    raw_sql = target.get("rawSql") or target.get("query") or target.get("rawQueryText")
                    if isinstance(raw_sql, str) and raw_sql.strip():
                        total_queries += 1
                        sub_sql = re.sub(r"\$__timeFilter\((.*?)\)", r"(\1 >= 0)", raw_sql)
                        sub_sql = re.sub(r"\$__time\((.*?)\)", r"\1", sub_sql)
                        sub_sql = re.sub(r"\$__timeGroup\((.*?),.*?\)", r"((\1 / 900000) * 900000)", sub_sql)
                        sub_sql = re.sub(r"\$__unixEpochFrom\(\)", "0", sub_sql)
                        sub_sql = re.sub(r"\$__unixEpochTo\(\)", "9999999999", sub_sql)
                        sub_sql = (
                            sub_sql.replace("$__timeFrom()", "0")
                            .replace("$__timeTo()", "9999999999999")
                            .replace("$__interval_ms", "1000")
                            .replace("$__interval", "1s")
                            .replace("$participant", "alice")
                            .replace("$experiment", "exp-1")
                            .replace("$strategy", "all")
                            .replace("$experiment_status", "all")
                            .replace("$min_trades", "0")
                        )
                        try:
                            cur.execute(sub_sql)
                        except Exception as e:
                            self.fail(f"Panel '{p.get('title')}' in '{dashboard.get('title')}' failed SQL:\n{sub_sql}\nError: {e}")

        self.assertEqual(total_queries, 25, f"Expected 25 SQL queries across 3 dashboards, got {total_queries}")


class TestGrafanaFolderAcls(unittest.TestCase):
    def test_enforce_folder_acls_default_deny(self):
        import tempfile
        import sqlite3
        from monitoring.grafana.enforce_folder_acls import enforce_acls

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.executescript("""
                CREATE TABLE dashboard (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT,
                    title TEXT,
                    is_folder INTEGER DEFAULT 0,
                    folder_id INTEGER DEFAULT 0,
                    has_acl INTEGER DEFAULT 0,
                    org_id INTEGER DEFAULT 1
                );
                CREATE TABLE dashboard_acl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id INTEGER NOT NULL,
                    dashboard_id INTEGER NOT NULL,
                    user_id INTEGER NULL,
                    team_id INTEGER NULL,
                    permission INTEGER NOT NULL DEFAULT 4,
                    role TEXT NULL,
                    created DATETIME NOT NULL,
                    updated DATETIME NOT NULL
                );
                CREATE TABLE role (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL
                );
                CREATE TABLE permission (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    scope TEXT NOT NULL
                );

                -- Initial state: global permissions
                INSERT INTO dashboard_acl (org_id, dashboard_id, permission, role, created, updated) VALUES
                    (1, -1, 1, 'Viewer', '2026-01-01', '2026-01-01'),
                    (1, -1, 2, 'Editor', '2026-01-01', '2026-01-01');

                -- Initial folders & child dashboard
                INSERT INTO dashboard (id, uid, title, is_folder, folder_id, org_id) VALUES
                    (10, 'infrastructure', 'Infrastructure', 1, 0, 1),
                    (11, 'financial-intelligence', 'Financial Intelligence', 1, 0, 1),
                    (12, 'btcupdown', 'BTC Up/Down', 1, 0, 1),
                    (20, 'infra-dash', 'Host Metrics', 0, 10, 1);

                -- Initial RBAC roles & permissions
                INSERT INTO role (id, name) VALUES (1, 'managed:builtins:viewer:permissions');
                INSERT INTO permission (role_id, action, scope) VALUES
                    (1, 'folders:read', 'folders:uid:infrastructure'),
                    (1, 'dashboards:read', 'folders:uid:infrastructure'),
                    (1, 'folders:read', 'folders:uid:btcupdown'),
                    (1, 'dashboards:read', 'folders:uid:btcupdown'),
                    (1, 'datasources:query', 'datasources:uid:actual-sqlite');
            """)
            conn.commit()
            conn.close()

            results = enforce_acls(db_path)
            self.assertEqual(results["global_viewers_removed"], 1)
            self.assertEqual(results["viewer_rbac_permissions_pruned"], 3)

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            # Verify has_acl: 1 for folders, 0 for child dashboards
            cur.execute("SELECT id, has_acl FROM dashboard ORDER BY id")
            dash_acls = dict(cur.fetchall())
            self.assertEqual(dash_acls[10], 1)
            self.assertEqual(dash_acls[11], 1)
            self.assertEqual(dash_acls[12], 1)
            self.assertEqual(dash_acls[20], 0)

            # Global check: no Viewer permission on dashboard_id = -1
            cur.execute("SELECT * FROM dashboard_acl WHERE dashboard_id = -1 AND role = 'Viewer'")
            self.assertIsNone(cur.fetchone())

            # Infrastructure: Editor (2) and Admin (4) only
            cur.execute("SELECT role, permission FROM dashboard_acl WHERE dashboard_id = 10")
            infra_acls = dict(cur.fetchall())
            self.assertNotIn("Viewer", infra_acls)
            self.assertEqual(infra_acls.get("Editor"), 2)
            self.assertEqual(infra_acls.get("Admin"), 4)

            # Financial Intelligence: Editor (2) and Admin (4) only
            cur.execute("SELECT role, permission FROM dashboard_acl WHERE dashboard_id = 11")
            fin_acls = dict(cur.fetchall())
            self.assertNotIn("Viewer", fin_acls)
            self.assertEqual(fin_acls.get("Editor"), 2)

            # BTC Up/Down: Viewer (1), Editor (2), and Admin (4)
            cur.execute("SELECT role, permission FROM dashboard_acl WHERE dashboard_id = 12")
            btc_acls = dict(cur.fetchall())
            self.assertEqual(btc_acls.get("Viewer"), 1)
            self.assertEqual(btc_acls.get("Editor"), 2)
            self.assertEqual(btc_acls.get("Admin"), 4)

            # RBAC permission check: Viewer only retains btcupdown
            cur.execute("SELECT action, scope FROM permission WHERE role_id = 1")
            viewer_perms = cur.fetchall()
            self.assertEqual(len(viewer_perms), 2)
            self.assertTrue(all(p[1] == "folders:uid:btcupdown" for p in viewer_perms))

            conn.close()


if __name__ == "__main__":
    unittest.main()
