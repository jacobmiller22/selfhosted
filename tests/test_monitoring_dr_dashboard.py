#!/usr/bin/env python3
"""
Unit tests validating Disaster Recovery & Backup Health Grafana Dashboard,
Prometheus textfile telemetry exporter script, and dashboard provisioning.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "monitoring" / "compose.yml"
DASHBOARDS_PROV_FILE = REPO_ROOT / "monitoring" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
DR_DASHBOARD_FILE = REPO_ROOT / "monitoring" / "grafana" / "dashboards" / "dr-and-backups.json"
EXPORTER_SCRIPT = REPO_ROOT / "tools" / "backup-dr" / "export-dr-metrics.sh"
README_FILE = REPO_ROOT / "monitoring" / "README.md"


class TestDRDashboardJSON(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(DR_DASHBOARD_FILE.exists(), f"{DR_DASHBOARD_FILE} must exist")
        with open(DR_DASHBOARD_FILE, "r", encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_dashboard_metadata(self):
        self.assertEqual(self.data.get("uid"), "dr-and-backups")
        self.assertIn("Disaster Recovery", self.data.get("title", ""))
        self.assertIn("Backup Health", self.data.get("title", ""))
        tags = self.data.get("tags", [])
        for expected_tag in ["backup", "dr", "rto", "rpo"]:
            self.assertIn(expected_tag, tags, f"Expected tag '{expected_tag}' in dashboard tags")

    def test_templating_variable(self):
        templating = self.data.get("templating", {}).get("list", [])
        self.assertTrue(len(templating) > 0, "Dashboard must declare template variables")
        service_var = next((v for v in templating if v.get("name") == "service"), None)
        self.assertIsNotNone(service_var, "Dashboard must have '$service' template variable")
        self.assertTrue(service_var.get("includeAll"), "Variable must support 'All' option")
        query_def = service_var.get("definition", "")
        if not query_def and isinstance(service_var.get("query"), dict):
            query_def = service_var["query"].get("query", "")
        self.assertIn("label_values(selfhosted_backup_last_timestamp_seconds, service)", str(query_def))

    def test_all_required_prometheus_metrics_queried(self):
        required_metrics = [
            "selfhosted_backup_last_timestamp_seconds",
            "selfhosted_backup_size_bytes",
            "selfhosted_backup_status",
            "selfhosted_dr_drill_rto_seconds",
            "selfhosted_dr_drill_rpo_seconds",
            "selfhosted_dr_drill_status",
        ]

        panels = self.data.get("panels", [])
        all_targets = []
        for panel in panels:
            all_targets.extend(panel.get("targets", []))

        all_exprs = " ".join(t.get("expr", "") for t in all_targets)

        for metric in required_metrics:
            self.assertIn(metric, all_exprs, f"Metric '{metric}' must be queried in dashboard panels")

    def test_plain_english_eli5_tooltips_on_all_visual_panels(self):
        panels = self.data.get("panels", [])
        visual_panels = [p for p in panels if p.get("type") not in ("row", "text")]
        self.assertTrue(len(visual_panels) >= 5, f"Expected at least 5 visual panels, got {len(visual_panels)}")

        for panel in visual_panels:
            title = panel.get("title", "Untitled")
            desc = panel.get("description", "")
            self.assertTrue(len(desc) > 30, f"Panel '{title}' must have a comprehensive description")
            self.assertIn("What is RTO?", desc, f"Panel '{title}' missing 'What is RTO?' in tooltip")
            self.assertIn("What is RPO?", desc, f"Panel '{title}' missing 'What is RPO?' in tooltip")
            self.assertIn("What should I do if this is red?", desc, f"Panel '{title}' missing 'What should I do if this is red?' in tooltip")

    def test_freshness_gauge_thresholds(self):
        panels = self.data.get("panels", [])
        gauge = next((p for p in panels if p.get("type") == "gauge" and "Freshness" in p.get("title", "")), None)
        self.assertIsNotNone(gauge, "Service Backup Freshness Gauge panel must exist")

        field_config = gauge.get("fieldConfig", {}).get("defaults", {})
        steps = field_config.get("thresholds", {}).get("steps", [])
        self.assertTrue(len(steps) >= 3, f"Freshness gauge must define at least 3 threshold steps, found: {steps}")

        # Check threshold colors: Green < 24h, Yellow 24-26h, Red > 26h
        step_colors = [s.get("color") for s in steps]
        self.assertEqual(step_colors[0], "green", "Base threshold must be green")
        self.assertIn(step_colors[1], ["yellow", "#EAB839", "#FADE2A"], "Intermediate threshold must be yellow")
        self.assertIn(step_colors[2], ["red", "#F2495C"], "Breach threshold must be red")

        # Values should be 24 and 26 (hours) or 86400 and 93600 (seconds)
        values = [s.get("value") for s in steps if s.get("value") is not None]
        is_hours = values == [24, 26]
        is_seconds = values == [86400, 93600]
        self.assertTrue(is_hours or is_seconds, f"Expected [24, 26] hours or [86400, 93600] seconds, got {values}")

    def test_dr_drill_status_stat_panel(self):
        panels = self.data.get("panels", [])
        stat_panel = next((p for p in panels if p.get("type") == "stat" and "Drill" in p.get("title", "")), None)
        self.assertIsNotNone(stat_panel, "DR Drill status panel must exist")
        exprs = [t.get("expr", "") for t in stat_panel.get("targets", [])]
        self.assertTrue(any("selfhosted_dr_drill_status" in e for e in exprs))

    def test_rto_and_rpo_trend_panels_present(self):
        panels = self.data.get("panels", [])
        rto_panel = next((p for p in panels if "RTO" in p.get("title", "") and p.get("type") == "timeseries"), None)
        rpo_panel = next((p for p in panels if "RPO" in p.get("title", "") and p.get("type") == "timeseries"), None)
        self.assertIsNotNone(rto_panel, "RTO trend panel must exist")
        self.assertIsNotNone(rpo_panel, "RPO trend panel must exist")

    def test_archive_size_panel_present(self):
        panels = self.data.get("panels", [])
        size_panel = next((p for p in panels if "Size" in p.get("title", "")), None)
        self.assertIsNotNone(size_panel, "Archive size panel must exist")


class TestDRMetricsExporterScript(unittest.TestCase):
    def test_script_exists_and_is_executable(self):
        self.assertTrue(EXPORTER_SCRIPT.exists(), f"{EXPORTER_SCRIPT} must exist")
        self.assertTrue(os.access(EXPORTER_SCRIPT, os.X_OK), f"{EXPORTER_SCRIPT} must be executable")

    def test_shellcheck_clean(self):
        shellcheck_bin = shutil.which("shellcheck")
        if not shellcheck_bin:
            self.skipTest("shellcheck not found on PATH")

        res = subprocess.run(
            [shellcheck_bin, "--severity=warning", str(EXPORTER_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"ShellCheck produced warnings:\n{res.stderr}\n{res.stdout}")

    def test_help_flag(self):
        for flag in ["-h", "--help"]:
            res = subprocess.run(
                [str(EXPORTER_SCRIPT), flag],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("Usage:", res.stdout)
            self.assertIn("--output", res.stdout)
            self.assertIn("--dry-run", res.stdout)
            self.assertIn("--service", res.stdout)

    def test_dry_run_generates_all_required_metrics(self):
        res = subprocess.run(
            [str(EXPORTER_SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(res.returncode, 0, f"Dry-run failed: {res.stderr}")
        stdout = res.stdout

        required_metrics = [
            "selfhosted_backup_last_timestamp_seconds",
            "selfhosted_backup_size_bytes",
            "selfhosted_backup_status",
            "selfhosted_dr_drill_rto_seconds",
            "selfhosted_dr_drill_rpo_seconds",
            "selfhosted_dr_drill_status",
        ]
        for m in required_metrics:
            self.assertIn(m, stdout, f"Metric '{m}' missing in exporter dry-run output")

        for svc in ["actual", "vaultwarden", "ha", "npm", "obsidian"]:
            self.assertIn(f'service="{svc}"', stdout, f"Service '{svc}' missing in exporter output")

    def test_output_file_generation_and_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prom_path = Path(tmpdir) / "test_backups.prom"
            state_path = Path(tmpdir) / "test_state.json"

            # Initial write
            res = subprocess.run(
                [
                    str(EXPORTER_SCRIPT),
                    "--output", str(prom_path),
                    "--state-file", str(state_path),
                    "--service", "actual",
                    "--backup-size", "20480000",
                    "--backup-status", "1",
                    "--rto", "42",
                    "--rpo", "1200",
                    "--drill-status", "1",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res.returncode, 0, f"Exporter failed: {res.stderr}")
            self.assertTrue(prom_path.exists(), "Output .prom file must be created")

            content = prom_path.read_text(encoding="utf-8")
            self.assertIn('selfhosted_backup_size_bytes{service="actual"} 20480000', content)
            self.assertIn('selfhosted_dr_drill_rto_seconds{service="actual"} 42', content)
            self.assertIn('selfhosted_dr_drill_rpo_seconds{service="actual"} 1200', content)
            self.assertIn('selfhosted_dr_drill_status 1', content)

            # Secondary update for vaultwarden preserving actual
            res2 = subprocess.run(
                [
                    str(EXPORTER_SCRIPT),
                    "--output", str(prom_path),
                    "--state-file", str(state_path),
                    "--service", "vaultwarden",
                    "--backup-size", "9999999",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(res2.returncode, 0)
            content2 = prom_path.read_text(encoding="utf-8")
            self.assertIn('selfhosted_backup_size_bytes{service="actual"} 20480000', content2)
            self.assertIn('selfhosted_backup_size_bytes{service="vaultwarden"} 9999999', content2)


class TestProvisioningAndDocumentation(unittest.TestCase):
    def test_dashboard_provisioning_config(self):
        self.assertTrue(DASHBOARDS_PROV_FILE.exists(), f"{DASHBOARDS_PROV_FILE} must exist")
        with open(DASHBOARDS_PROV_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        providers = data.get("providers", [])
        self.assertTrue(len(providers) > 0, "At least one provider must be declared")
        provider = providers[0]
        options = provider.get("options", {})
        self.assertEqual(options.get("path"), "/var/lib/grafana/dashboards")

    def test_compose_node_exporter_textfile_collector(self):
        with open(COMPOSE_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        ne = data.get("services", {}).get("node-exporter", {})
        cmd = " ".join(ne.get("command", []))
        self.assertIn("--collector.textfile.directory=/host/var/lib/node_exporter/textfile_collector", cmd)

    def test_readme_documents_dashboard_and_metrics(self):
        self.assertTrue(README_FILE.exists())
        text = README_FILE.read_text(encoding="utf-8")
        self.assertIn("dr-and-backups.json", text)
        self.assertIn("dr-and-backups", text)
        self.assertIn("selfhosted_backup_last_timestamp_seconds", text)
        self.assertIn("selfhosted_dr_drill_rto_seconds", text)
        self.assertIn("What is RTO?", text)
        self.assertIn("What is RPO?", text)


if __name__ == "__main__":
    unittest.main()
