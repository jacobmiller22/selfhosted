#!/usr/bin/env python3
"""
Unit and Integration Tests for PM Architectural Council & Fact-Checking Engine.
"""

import unittest
from pathlib import Path
from tools.pm_architect.engine.fact_checker import RealityFactChecker, FactCheckFinding, CodebaseInventory
from tools.pm_architect.engine.council import (
    DeliberationCouncil, SystemsArchitect, SoftwareEngineer,
    SecuritySpecialist, SiteReliabilityEngineer, SeniorTPM
)
from tools.pm_architect.engine.dictator import BenevolentDictator
from tools.pm_architect.engine.graph import DependencyEngine, IssueNode
from tools.pm_architect.engine.tickets import TicketGenerator
from tools.pm_architect.engine.reporter import SynthesisReporter


class TestFactChecker(unittest.TestCase):
    def setUp(self):
        self.checker = RealityFactChecker()

    def test_codebase_inventory_contains_core_services(self):
        services = self.checker.inventory.services
        self.assertIn("actual_server", services)
        self.assertIn("vaultwarden", services)
        self.assertIn("nginx-proxy-manager", services)
        self.assertIn("homeassistant", services)

    def test_fact_check_valid_file(self):
        issue = {
            "number": 101,
            "title": "feat(docs): Update restoration procedures",
            "body": "Referencing docs/RESTORE.md and docs/BACKUP_ARCHITECTURE.md."
        }
        res = self.checker.check_issue(issue)
        self.assertEqual(res.overall_status, "VERIFIED")
        self.assertTrue(any("docs/RESTORE.md" in v for v in res.verified_items))

    def test_fact_check_missing_path(self):
        issue = {
            "number": 102,
            "title": "feat(legacy): Update non-existent script",
            "body": "Modify tools/deprecated/old-script.sh."
        }
        res = self.checker.check_issue(issue)
        self.assertEqual(res.overall_status, "WARNING_DRIFT")
        self.assertTrue(any("tools/deprecated/old-script.sh" in m for m in res.missing_assets))

    def test_fact_check_detects_assumptions(self):
        issue = {
            "number": 103,
            "title": "feat(spike): API testing",
            "body": "Assumes that external Coolify API supports batch operations."
        }
        res = self.checker.check_issue(issue)
        self.assertEqual(res.overall_status, "NEEDS_RESEARCH")
        self.assertTrue(len(res.unverified_assumptions) > 0)

    def test_fact_check_ignores_natural_language_slashes_and_cli_tokens(self):
        issue = {
            "number": 104,
            "title": "feat(core): Cross-platform support",
            "body": "Supports macOS/Linux and Node.js/TypeScript. Handles S3/B2 sync, rx/tx stats, 24/7 uptime, and I/O rates (100 kB/s)."
        }
        res = self.checker.check_issue(issue)
        self.assertEqual(res.overall_status, "VERIFIED")
        self.assertEqual(len(res.missing_assets), 0)

    def test_fact_check_recognizes_checklist_deliverables(self):
        issue = {
            "number": 105,
            "title": "feat(tool): Build new healthcheck tool",
            "body": "### Deliverables\n- [ ] `tools/healthcheck.sh`\n- [ ] Create `tools/monitor.py`"
        }
        res = self.checker.check_issue(issue)
        self.assertEqual(res.overall_status, "VERIFIED")
        self.assertTrue(any("tools/healthcheck.sh" in v for v in res.verified_items))
        self.assertTrue(any("tools/monitor.py" in v for v in res.verified_items))


class TestCouncilPersonas(unittest.TestCase):
    def setUp(self):
        self.council = DeliberationCouncil()
        self.checker = RealityFactChecker()

    def test_systems_architect_flags_port_collisions(self):
        issue = {
            "number": 104,
            "title": "feat(service): Deploy new container on port 80",
            "body": "Binding host port 80 for web interface."
        }
        res = self.checker.check_issue(issue)
        review = SystemsArchitect().evaluate(issue, res, self.checker.inventory)
        self.assertIn(review.verdict, ["REQUEST_CHANGES", "FLAG_RISK"])
        self.assertTrue(any("80" in r for r in review.risks))

    def test_security_specialist_flags_database_without_backup(self):
        issue = {
            "number": 105,
            "title": "feat(actual): Direct database schema migration",
            "body": "Mutate sqlite database tables in Actual Budget container directly."
        }
        res = self.checker.check_issue(issue)
        review = SecuritySpecialist().evaluate(issue, res, self.checker.inventory)
        self.assertEqual(review.verdict, "FLAG_RISK")
        self.assertTrue(any("database" in r.lower() for r in review.risks))

    def test_sre_flags_docker_socket_elevation(self):
        issue = {
            "number": 106,
            "title": "feat(tool): Container manager",
            "body": "Mount /var/run/docker.sock into unprivileged container."
        }
        res = self.checker.check_issue(issue)
        review = SiteReliabilityEngineer().evaluate(issue, res, self.checker.inventory)
        self.assertEqual(review.verdict, "FLAG_RISK")
        self.assertTrue(any("docker.sock" in r for r in review.risks))

    def test_tpm_flags_missing_acceptance_criteria(self):
        issue = {
            "number": 107,
            "title": "feat(tool): Vague task without checklist",
            "body": "Do some refactoring on the codebase.",
            "labels": [{"name": "priority:medium"}]
        }
        res = self.checker.check_issue(issue)
        review = SeniorTPM().evaluate(issue, res, self.checker.inventory)
        self.assertTrue(any("checkboxes" in r for r in review.risks))


class TestBenevolentDictator(unittest.TestCase):
    def setUp(self):
        self.dictator = BenevolentDictator()
        self.checker = RealityFactChecker()
        self.council = DeliberationCouncil()

    def test_dictator_mandates_containment_for_docker_sock(self):
        issue = {
            "number": 108,
            "title": "feat(runner): Ephemeral runner",
            "body": "Mounts docker.sock for automated container builds."
        }
        fc = self.checker.check_issue(issue)
        delib = self.council.deliberate(issue, fc, self.checker.inventory)
        ruling = self.dictator.arbitrate(issue, fc, delib, self.checker.inventory)

        self.assertEqual(ruling.binding_verdict, "AMENDED_WITH_CONSTRAINTS")
        self.assertIn("CONTAINMENT MANDATE", ruling.mandated_safeguards[0])

    def test_dictator_vetoes_overengineering_under_axiom_3(self):
        issue = {
            "number": 109,
            "title": "feat(infra): Migrate homelab to Kubernetes cluster",
            "body": "Deploy k8s multi-master control plane across single server."
        }
        fc = self.checker.check_issue(issue)
        delib = self.council.deliberate(issue, fc, self.checker.inventory)
        ruling = self.dictator.arbitrate(issue, fc, delib, self.checker.inventory)

        self.assertEqual(ruling.binding_verdict, "VETOED")
        self.assertTrue(any("VETOED UNDER AXIOM 3" in v for v in ruling.veto_reasons))


class TestDependencyEngine(unittest.TestCase):
    def setUp(self):
        self.engine = DependencyEngine()

    def test_dependency_extraction_and_topological_sort(self):
        issues = [
            {"number": 1, "title": "Base infrastructure", "labels": [{"name": "priority:high"}], "body": ""},
            {"number": 2, "title": "Mid layer service", "labels": [{"name": "priority:high"}], "body": "Prerequisites: #1"},
            {"number": 3, "title": "Top application", "labels": [{"name": "priority:medium"}], "body": "Blocked by: #2"}
        ]
        g = self.engine.build_graph(issues)
        self.assertEqual(g.shovel_ready_sequence, [1])
        self.assertEqual(g.blocked_issues[2], [1])
        self.assertEqual(g.blocked_issues[3], [2])

    def test_cycle_detection(self):
        issues = [
            {"number": 1, "title": "Task A", "labels": [], "body": "Prerequisites: #2"},
            {"number": 2, "title": "Task B", "labels": [], "body": "Prerequisites: #1"}
        ]
        g = self.engine.build_graph(issues)
        self.assertTrue(len(g.cycles) > 0)


class TestTicketGeneratorAndReporter(unittest.TestCase):
    def setUp(self):
        self.generator = TicketGenerator()
        self.checker = RealityFactChecker()
        self.council = DeliberationCouncil()
        self.dictator = BenevolentDictator()
        self.reporter = SynthesisReporter("test/repo")

    def test_generates_spike_and_reconciliation_tickets(self):
        issue = {
            "number": 200,
            "title": "feat(test): Unknown performance",
            "body": "Untested API latency under high concurrency. Uses rclone copy directly."
        }
        fc = self.checker.check_issue(issue)
        delib = self.council.deliberate(issue, fc, self.checker.inventory)
        ruling = self.dictator.arbitrate(issue, fc, delib, self.checker.inventory)

        tickets = self.generator.generate_tickets(
            {200: fc}, {200: delib}, {200: ruling}, self.checker.inventory
        )

        types = [t.ticket_type for t in tickets]
        self.assertIn("SPIKE", types)
        self.assertIn("RECONCILIATION", types)

    def test_report_generation(self):
        issue = {"number": 1, "title": "Task", "labels": [{"name": "priority:high"}], "body": ""}
        fc = self.checker.check_issue(issue)
        delib = self.council.deliberate(issue, fc, self.checker.inventory)
        ruling = self.dictator.arbitrate(issue, fc, delib, self.checker.inventory)
        g = DependencyEngine().build_graph([issue])

        report = self.reporter.generate_report(
            issues=[issue],
            inventory=self.checker.inventory,
            fact_checks={1: fc},
            deliberations={1: delib},
            rulings={1: ruling},
            graph=g,
            proposed_tickets=[]
        )
        self.assertIn("# 🏛️ Backlog Synthesis & Architectural Council Report", report)
        self.assertIn("Backlog Health Score", report)
        self.assertIn("Benevolent Dictator", report)


if __name__ == "__main__":
    unittest.main()
