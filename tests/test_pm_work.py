#!/usr/bin/env python3
"""
Unit and Integration Tests for PM Autonomous Planning Interval Super-Loop Engine ('pm work').
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.pm_architect.engine.fact_checker import RealityFactChecker, IssueFactCheckResult, CodebaseInventory
from tools.pm_architect.engine.stakeholders import (
    StakeholderCouncil, StorageAndBackupStakeholder, NetworkingIngressStakeholder,
    DatabaseSchemaStakeholder, ServiceIntegrationStakeholder, HistoricalCodebaseStakeholder
)
from tools.pm_architect.engine.state_manager import (
    StateManager, GitHubProgressTracker, PlanningIntervalState, WaveState, TaskState
)
from tools.pm_architect.engine.work_orchestrator import WorkOrchestrator, WorkerManifest
from tools.pm_architect.engine.watchdog import TaskWatchdog, TaskWatchdogState, WatchdogPolicy


class TestDomainStakeholders(unittest.TestCase):
    def setUp(self):
        self.checker = RealityFactChecker()
        self.inventory = self.checker.inventory

    def test_storage_stakeholder_flags_raw_sqlite_cp(self):
        stakeholder = StorageAndBackupStakeholder()
        issues = [{
            "number": 201,
            "title": "feat(actual): Direct database copy script",
            "body": "Run cp /data/actual.sqlite /backup/actual.sqlite before container restart."
        }]
        fact_checks = {201: self.checker.check_issue(issues[0])}
        res = stakeholder.audit(issues, fact_checks, self.inventory)
        self.assertTrue(res.has_critical_blockers)
        self.assertTrue(any("Direct filesystem copy" in f.summary for f in res.findings))

    def test_storage_stakeholder_flags_missing_pbkdf2(self):
        stakeholder = StorageAndBackupStakeholder()
        issues = [{
            "number": 202,
            "title": "feat(backup): Encrypt snapshot archives",
            "body": "Run openssl aes-256-cbc -e -in dump.sql -out dump.sql.enc"
        }]
        fact_checks = {202: self.checker.check_issue(issues[0])}
        res = stakeholder.audit(issues, fact_checks, self.inventory)
        self.assertTrue(any("-pbkdf2" in f.summary for f in res.findings))

    def test_network_stakeholder_flags_port_collision(self):
        stakeholder = NetworkingIngressStakeholder()
        # Port 80 is mapped by nginx-proxy-manager in inventory
        issues = [{
            "number": 203,
            "title": "feat(metrics): Expose web metrics dashboard",
            "body": "Binding host port 80 for public prometheus metrics."
        }]
        fact_checks = {203: self.checker.check_issue(issues[0])}
        res = stakeholder.audit(issues, fact_checks, self.inventory)
        self.assertTrue(res.has_critical_blockers)
        self.assertTrue(any("Port collision" in f.summary for f in res.findings))

    def test_database_stakeholder_flags_missing_rollback(self):
        stakeholder = DatabaseSchemaStakeholder()
        issues = [{
            "number": 204,
            "title": "feat(db): Schema alteration for user accounts",
            "body": "Execute table migration to add auth_token column to users table."
        }]
        fact_checks = {204: self.checker.check_issue(issues[0])}
        res = stakeholder.audit(issues, fact_checks, self.inventory)
        self.assertTrue(any("rollback" in f.summary.lower() for f in res.findings))

    def test_service_integration_stakeholder_flags_missing_healthcheck(self):
        stakeholder = ServiceIntegrationStakeholder()
        issues = [{
            "number": 205,
            "title": "feat(infra): Deploy new telemetry container",
            "body": "Add new container definition in docker-compose.yml."
        }]
        fact_checks = {205: self.checker.check_issue(issues[0])}
        res = stakeholder.audit(issues, fact_checks, self.inventory)
        self.assertTrue(any("healthcheck" in f.summary.lower() for f in res.findings))

    def test_stakeholder_council_synthesis_sorts_by_severity(self):
        council = StakeholderCouncil()
        issues = [
            {
                "number": 206,
                "title": "feat(actual): Direct database copy",
                "body": "Run cp /data/actual.sqlite /backup/"
            },
            {
                "number": 207,
                "title": "feat(db): Table migration",
                "body": "Execute schema migration."
            }
        ]
        fact_checks = {i["number"]: self.checker.check_issue(i) for i in issues}
        audit_results = council.audit_backlog(issues, fact_checks, self.inventory)
        findings = council.synthesize_gaps(audit_results)
        self.assertTrue(len(findings) >= 2)
        # CRITICAL findings must come first
        self.assertEqual(findings[0].severity, "CRITICAL")


class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.state_mgr = StateManager(repo_path=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_state_save_and_load(self):
        task1 = TaskState(issue_number=101, title="feat(db): Core setup", status="completed", pr_number=12, pr_url="https://github.com/pr/12")
        task2 = TaskState(issue_number=102, title="feat(api): Endpoints", status="in_progress")
        wave1 = WaveState(wave_id=1, status="in_progress", tasks={"101": task1, "102": task2}, disjoint_modules=["db", "api"])

        pi_state = PlanningIntervalState(
            pi_number=2,
            pi_issue_number=99,
            vision="Automate disaster recovery failover",
            milestone="v2.0",
            phase="WAVE_EXECUTION",
            current_wave_index=0,
            waves=[wave1],
            gaps_created=[105],
            council_rulings_summary=["Enforce readonly socket"],
            stakeholder_findings_summary=["SQLite WAL checkpoint required"],
            completed_issues=[101]
        )

        self.state_mgr.save_state(pi_state)
        loaded = self.state_mgr.load_state()

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.pi_number, 2)
        self.assertEqual(loaded.pi_issue_number, 99)
        self.assertEqual(loaded.vision, "Automate disaster recovery failover")
        self.assertEqual(len(loaded.waves), 1)
        self.assertEqual(loaded.waves[0].tasks["101"].status, "completed")
        self.assertEqual(loaded.waves[0].tasks["101"].pr_number, 12)
        self.assertIn(101, loaded.completed_issues)

    def test_github_progress_tracker_body_formatting(self):
        tracker = GitHubProgressTracker(repo="owner/test-repo")
        task1 = TaskState(issue_number=101, title="feat(db): Core setup", status="completed", pr_number=12, pr_url="https://github.com/owner/test-repo/pull/12")
        task2 = TaskState(issue_number=102, title="feat(api): Endpoints", status="pending")
        wave = WaveState(wave_id=1, status="in_progress", tasks={"101": task1, "102": task2}, disjoint_modules=["db", "api"])

        body = tracker.format_pi_story_body(
            pi_number=1,
            vision="Complete automated backups",
            waves=[wave],
            council_summary=["Axiom 2: Zero data loss"],
            stakeholder_summary=["Storage: Enforce sqlite .backup"]
        )

        self.assertIn("## 🎯 Planning Interval PI-1 Vision & Objectives", body)
        self.assertIn("Complete automated backups", body)
        self.assertIn("- [x] #101 - feat(db): Core setup ([PR #12](https://github.com/owner/test-repo/pull/12))", body)
        self.assertIn("- [ ] #102 - feat(api): Endpoints", body)
        self.assertIn("Axiom 2: Zero data loss", body)
        self.assertIn("Storage: Enforce sqlite .backup", body)


class TestWorkOrchestrator(unittest.TestCase):
    def setUp(self):
        self.orchestrator = WorkOrchestrator(repo="owner/test-repo", max_workers_per_wave=3)

    def test_extract_module_for_issue(self):
        inv = self.orchestrator.fact_checker.inventory
        issue_actual = {"title": "feat(actual): Backup runner integration", "body": ""}
        issue_docs = {"title": "docs(dr): Restore guide", "body": ""}
        issue_unscoped = {"title": "Refactor tools/monitor.py", "body": "Inspect tools/monitor.py"}

        self.assertEqual(self.orchestrator.extract_module_for_issue(issue_actual, inv), "actual")
        self.assertEqual(self.orchestrator.extract_module_for_issue(issue_docs, inv), "dr")
        self.assertEqual(self.orchestrator.extract_module_for_issue(issue_unscoped, inv), "tools")

    def test_extract_thinking_tier(self):
        self.assertEqual(self.orchestrator.extract_thinking_tier("**Thinking Level**: High\nDetails"), "High")
        self.assertEqual(self.orchestrator.extract_thinking_tier("Complex database migration with locking"), "High")
        self.assertEqual(self.orchestrator.extract_thinking_tier("Update typo in README documentation"), "Low")

    def test_partition_into_waves_respects_dependencies_and_disjointness(self):
        inv = self.orchestrator.fact_checker.inventory
        issues = [
            {
                "number": 1,
                "title": "feat(actual): Database snapshot runner",
                "body": "Prerequisites: none",
                "labels": [{"name": "priority:high"}]
            },
            {
                "number": 2,
                "title": "feat(vaultwarden): Vaultwarden backup volume",
                "body": "Prerequisites: none",
                "labels": [{"name": "priority:high"}]
            },
            {
                "number": 3,
                "title": "feat(actual): Actual Budget UI alert",
                "body": "Depends on: #1",  # Blocked by #1
                "labels": [{"name": "priority:medium"}]
            },
            {
                "number": 4,
                "title": "docs(dr): Backup runbook",
                "body": "Depends on: #1 and #2",  # Blocked by #1 and #2
                "labels": [{"name": "priority:low"}]
            }
        ]

        closed_numbers = set()
        waves = self.orchestrator.partition_into_waves(issues, closed_numbers, inv)

        # Wave 1 must contain #1 and #2 (both independent and touching disjoint modules: actual vs vaultwarden)
        self.assertEqual(len(waves), 2)
        wave1_nums = set(int(k) for k in waves[0].tasks.keys())
        self.assertIn(1, wave1_nums)
        self.assertIn(2, wave1_nums)

        # Wave 2 must contain #3 and #4 (which depended on #1 and #2)
        wave2_nums = set(int(k) for k in waves[1].tasks.keys())
        self.assertIn(3, wave2_nums)
        self.assertIn(4, wave2_nums)

    def test_build_worker_manifests(self):
        wave = WaveState(
            wave_id=1,
            tasks={
                "1": TaskState(issue_number=1, title="feat(actual): Backup runner", status="pending")
            },
            disjoint_modules=["actual"]
        )
        all_issues = {
            1: {
                "number": 1,
                "title": "feat(actual): Backup runner",
                "body": "Implement backup runner. Run `pnpm test`."
            }
        }
        manifests = self.orchestrator.build_worker_manifests(wave, all_issues, "main", parent_pi_story=99)
        self.assertEqual(len(manifests), 1)
        m = manifests[0]
        self.assertEqual(m.issue_number, 1)
        self.assertEqual(m.branch_name, "feature/task-1-backup-runner")
        self.assertEqual(m.base_branch, "main")
        self.assertEqual(m.parent_pi_story, 99)
        self.assertIn("pnpm test", m.verification_commands)
        self.assertGreater(m.inactivity_timeout_seconds, 0)
        self.assertGreater(m.max_execution_timeout_seconds, 0)


class TestTaskWatchdog(unittest.TestCase):
    def setUp(self):
        self.watchdog = TaskWatchdog()
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_inactivity_timeout_detection(self):
        # Task started 400s ago, last activity 400s ago (exceeds Low thinking 180s inactivity limit)
        state = TaskWatchdogState(
            issue_number=301,
            thinking_tier="Low",
            worktree_path=self.temp_dir,
            started_at=1000.0,
            last_activity_at=1000.0
        )
        is_healthy, reason = self.watchdog.evaluate(state, current_time=1400.0)
        self.assertFalse(is_healthy)
        self.assertTrue(state.is_timed_out)
        self.assertIn("Stagnation Detected", reason)

    def test_execution_ceiling_detection(self):
        # Task started 700s ago (exceeds Low thinking 600s max execution limit)
        state = TaskWatchdogState(
            issue_number=302,
            thinking_tier="Low",
            worktree_path=self.temp_dir,
            started_at=1000.0,
            last_activity_at=1650.0  # Recent activity, but overall ceiling exceeded
        )
        is_healthy, reason = self.watchdog.evaluate(state, current_time=1700.0)
        self.assertFalse(is_healthy)
        self.assertTrue(state.is_timed_out)
        self.assertIn("Execution Ceiling Exceeded", reason)

    def test_premature_timeout_prevention_via_liveness(self):
        # Simulate active work in worktree by creating a dirty file
        test_file = self.temp_dir / "active_work.ts"
        test_file.write_text("console.log('working');")

        state = TaskWatchdogState(
            issue_number=303,
            thinking_tier="Low",
            worktree_path=self.temp_dir,
            started_at=1000.0,
            last_activity_at=1000.0  # Would be stagnant without liveness check
        )
        # Evaluate at 1200s (exceeds 180s inactivity, but file was written now)
        is_healthy, reason = self.watchdog.evaluate(state, current_time=1200.0)
        self.assertTrue(is_healthy)
        self.assertFalse(state.is_timed_out)
        self.assertEqual(state.extensions_granted, 1)
        self.assertIn("Grace extension", reason)


if __name__ == "__main__":
    unittest.main()
