#!/usr/bin/env python3
"""
Domain Stakeholder Council & Historical Codebase Review Engine for 'pm work'.
Convenes individual domain stakeholders (Storage, Ingress, Database, Service Integration,
and Historical Git Blame / Commit Veterans) to audit candidate backlog issues and uncover
gaps, regressions, and unhandled edge cases before execution begins.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .fact_checker import IssueFactCheckResult, CodebaseInventory


@dataclass
class StakeholderFinding:
    stakeholder_name: str
    stakeholder_title: str
    severity: str  # CRITICAL, WARNING, INFO
    category: str  # MISSING_PREREQUISITE, REGRESSION_RISK, UNHANDLED_FAILURE_MODE, VERIFICATION_GAP
    issue_number: int
    summary: str
    details: str
    suggested_action: str


@dataclass
class StakeholderAuditResult:
    stakeholder_name: str
    stakeholder_title: str
    findings: List[StakeholderFinding] = field(default_factory=list)
    has_critical_blockers: bool = False
    gaps_identified: List[str] = field(default_factory=list)


class DomainStakeholder:
    def __init__(self, name: str, title: str, domain: str, focus_areas: List[str]):
        self.name = name
        self.title = title
        self.domain = domain
        self.focus_areas = focus_areas

    def audit(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory,
        repo_path: Optional[Path] = None
    ) -> StakeholderAuditResult:
        raise NotImplementedError


class StorageAndBackupStakeholder(DomainStakeholder):
    def __init__(self):
        super().__init__(
            name="storage_backup_custodian",
            title="Storage & Backup Custodian",
            domain="Data Persistence, SQLite WAL, Encryption, and Offsite Retention",
            focus_areas=[
                "SQLite WAL file locking and concurrent access safety",
                "Non-destructive snapshot commands (.backup instead of raw cp)",
                "AES-256-CBC PBKDF2 encryption integrity",
                "B2 and offsite retention rotation",
                "Persistent volume path validity and read-only mounts"
            ]
        )

    def audit(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory,
        repo_path: Optional[Path] = None
    ) -> StakeholderAuditResult:
        findings: List[StakeholderFinding] = []
        gaps: List[str] = []

        for issue in issues:
            num = issue.get("number", 0)
            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            combined = f"{title}\n{body}".lower()

            # Check for direct SQLite copy or lock risks
            if "sqlite" in combined or "database" in combined:
                if "cp " in combined and ".backup" not in combined:
                    findings.append(StakeholderFinding(
                        stakeholder_name=self.name,
                        stakeholder_title=self.title,
                        severity="CRITICAL",
                        category="REGRESSION_RISK",
                        issue_number=num,
                        summary="Direct filesystem copy of active SQLite database detected",
                        details="Issue references copying active SQLite database without utilizing sqlite3 '.backup', risking database corruption under concurrent write loads.",
                        suggested_action="Enforce sqlite3 snapshot command (.backup) in the task acceptance criteria."
                    ))
                    gaps.append(f"Issue #{num}: Missing atomic SQLite snapshot requirement.")

                if "backup" in combined and "wal" not in combined and "lock" not in combined:
                    findings.append(StakeholderFinding(
                        stakeholder_name=self.name,
                        stakeholder_title=self.title,
                        severity="WARNING",
                        category="UNHANDLED_FAILURE_MODE",
                        issue_number=num,
                        summary="SQLite WAL journal handling unspecified in backup routine",
                        details="SQLite databases with WAL mode enabled require copying both .wal and .shm journals or executing a checkpoint before snapshot.",
                        suggested_action="Specify checkpointing or atomic snapshot verification in deliverables."
                    ))

            # Check encryption passphrase handling
            if "encrypt" in combined or "openssl" in combined:
                if "pbkdf2" not in combined and "-pbkdf2" not in combined:
                    findings.append(StakeholderFinding(
                        stakeholder_name=self.name,
                        stakeholder_title=self.title,
                        severity="WARNING",
                        category="VERIFICATION_GAP",
                        issue_number=num,
                        summary="OpenSSL encryption missing explicit -pbkdf2 parameter",
                        details="Standard AES-256-CBC scripts must explicitly enforce -pbkdf2 -iter 100000 to maintain cross-version compatibility.",
                        suggested_action="Mandate '-pbkdf2' iteration flag in task acceptance criteria."
                    ))

        has_critical = any(f.severity == "CRITICAL" for f in findings)
        return StakeholderAuditResult(
            stakeholder_name=self.name,
            stakeholder_title=self.title,
            findings=findings,
            has_critical_blockers=has_critical,
            gaps_identified=gaps
        )


class NetworkingIngressStakeholder(DomainStakeholder):
    def __init__(self):
        super().__init__(
            name="networking_ingress_specialist",
            title="Networking & Ingress Specialist",
            domain="Reverse Proxy Routes, Ports, SSL/TLS, and DNS",
            focus_areas=[
                "Host port mapping and port collisions",
                "Reverse proxy bridge network attachment",
                "Tailscale MagicDNS vs Public SSL endpoints",
                "WebSocket upgrade header preservation",
                "SSL certificate path validation"
            ]
        )

    def audit(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory,
        repo_path: Optional[Path] = None
    ) -> StakeholderAuditResult:
        findings: List[StakeholderFinding] = []
        gaps: List[str] = []

        for issue in issues:
            num = issue.get("number", 0)
            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            combined = f"{title}\n{body}".lower()

            # Port collision checks
            for port, svc in inventory.ports_mapped.items():
                if f":{port}" in combined or f"port {port}" in combined:
                    if svc.lower() not in title.lower() and svc.lower() not in combined:
                        findings.append(StakeholderFinding(
                            stakeholder_name=self.name,
                            stakeholder_title=self.title,
                            severity="CRITICAL",
                            category="REGRESSION_RISK",
                            issue_number=num,
                            summary=f"Port collision: Port {port} is already claimed by {svc}",
                            details=f"The proposed task attempts to allocate or bind host port {port}, which is actively in use by {svc}.",
                            suggested_action=f"Reassign service to an unused port or route internally via reverse proxy bridge network."
                        ))
                        gaps.append(f"Issue #{num}: Port collision on port {port}.")

            # Ingress & WebSocket checks
            if "websocket" in combined or "homeassistant" in combined or "actual" in combined:
                if "reverse proxy" in combined or "npm" in combined:
                    if "upgrade" not in combined and "ws" not in combined:
                        findings.append(StakeholderFinding(
                            stakeholder_name=self.name,
                            stakeholder_title=self.title,
                            severity="WARNING",
                            category="UNHANDLED_FAILURE_MODE",
                            issue_number=num,
                            summary="WebSocket proxying missing Upgrade header configuration",
                            details="Reverse proxy config must pass 'Upgrade $http_upgrade' and 'Connection $connection_upgrade' headers for persistent WebSocket sessions.",
                            suggested_action="Add WebSocket proxy header verification to acceptance criteria."
                        ))

        has_critical = any(f.severity == "CRITICAL" for f in findings)
        return StakeholderAuditResult(
            stakeholder_name=self.name,
            stakeholder_title=self.title,
            findings=findings,
            has_critical_blockers=has_critical,
            gaps_identified=gaps
        )


class DatabaseSchemaStakeholder(DomainStakeholder):
    def __init__(self):
        super().__init__(
            name="database_schema_custodian",
            title="Database & Data Modeling Custodian",
            domain="Relational Integrity, Migrations, and Zero-Data-Loss Schema Evolution",
            focus_areas=[
                "Reversible schema migrations (up/down scripts)",
                "Transactional table alterations",
                "Column additions without destructive defaults",
                "Foreign key constraint integrity",
                "Index optimization for write/read amplification"
            ]
        )

    def audit(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory,
        repo_path: Optional[Path] = None
    ) -> StakeholderAuditResult:
        findings: List[StakeholderFinding] = []
        gaps: List[str] = []

        for issue in issues:
            num = issue.get("number", 0)
            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            combined = f"{title}\n{body}".lower()

            if "schema" in combined or "migration" in combined or "table" in combined:
                if "rollback" not in combined and "down" not in combined:
                    findings.append(StakeholderFinding(
                        stakeholder_name=self.name,
                        stakeholder_title=self.title,
                        severity="WARNING",
                        category="MISSING_PREREQUISITE",
                        issue_number=num,
                        summary="Schema migration lacks explicit rollback/down migration strategy",
                        details="Proposed database alteration does not specify atomic rollback procedure in event of migration failure.",
                        suggested_action="Require atomic transaction wrap (BEGIN TRANSACTION...COMMIT) and rollback plan."
                    ))
                    gaps.append(f"Issue #{num}: Missing migration rollback plan.")

        has_critical = any(f.severity == "CRITICAL" for f in findings)
        return StakeholderAuditResult(
            stakeholder_name=self.name,
            stakeholder_title=self.title,
            findings=findings,
            has_critical_blockers=has_critical,
            gaps_identified=gaps
        )


class ServiceIntegrationStakeholder(DomainStakeholder):
    def __init__(self):
        super().__init__(
            name="service_integration_lead",
            title="Service Integration & Microservices Lead",
            domain="Inter-Service Communication, Environment Variables, and API Contracts",
            focus_areas=[
                "Inter-container DNS resolution and bridge networks",
                "Environment variable propagation and secret injection",
                "Container healthcheck latches and start-period grace times",
                "Graceful degradation on downstream dependency outage"
            ]
        )

    def audit(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory,
        repo_path: Optional[Path] = None
    ) -> StakeholderAuditResult:
        findings: List[StakeholderFinding] = []
        gaps: List[str] = []

        for issue in issues:
            num = issue.get("number", 0)
            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            combined = f"{title}\n{body}".lower()

            # Check container healthcheck declarations
            if "deploy" in combined or "container" in combined or "docker-compose" in combined:
                if "healthcheck" not in combined and "compose" in combined:
                    findings.append(StakeholderFinding(
                        stakeholder_name=self.name,
                        stakeholder_title=self.title,
                        severity="INFO",
                        category="VERIFICATION_GAP",
                        issue_number=num,
                        summary="New container service missing explicit healthcheck latch",
                        details="Services should declare test/interval/timeout/retries in docker compose to integrate cleanly with ODVP Layer 1 monitoring.",
                        suggested_action="Add healthcheck definition to docker compose configuration."
                    ))

        has_critical = any(f.severity == "CRITICAL" for f in findings)
        return StakeholderAuditResult(
            stakeholder_name=self.name,
            stakeholder_title=self.title,
            findings=findings,
            has_critical_blockers=has_critical,
            gaps_identified=gaps
        )


class HistoricalCodebaseStakeholder(DomainStakeholder):
    def __init__(self):
        super().__init__(
            name="historical_codebase_stakeholder",
            title="Historical Codebase Stakeholder & Git Veteran",
            domain="Git Blame Telemetry, Past Commit Decisions, and Regression Avoidance",
            focus_areas=[
                "Recent commits touching referenced paths",
                "Past bugfixes and regression hazards in modified files",
                "Architectural rationale behind existing non-obvious implementations",
                "Authoritative domain context from code commit history"
            ]
        )

    def audit(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory,
        repo_path: Optional[Path] = None
    ) -> StakeholderAuditResult:
        findings: List[StakeholderFinding] = []
        gaps: List[str] = []
        repo_root = repo_path or Path.cwd()

        for issue in issues:
            num = issue.get("number", 0)
            fc = fact_checks.get(num)
            if not fc:
                continue

            # Query git history for verified assets to extract historical context
            target_files = [item for item in fc.verified_items if (repo_root / item).is_file()]
            for rel_file in target_files[:3]:  # Top 3 files
                try:
                    res = subprocess.check_output(
                        ["git", "log", "-n", "3", "--format=%h|%an|%s", "--", rel_file],
                        cwd=str(repo_root),
                        stderr=subprocess.DEVNULL
                    )
                    log_lines = res.decode("utf-8").strip().splitlines()
                    for line in log_lines:
                        parts = line.split("|", 2)
                        if len(parts) == 3:
                            sha, author, subject = parts
                            subj_lower = subject.lower()
                            # Check for regression indicators in past commits
                            if any(k in subj_lower for k in ["fix", "revert", "regression", "workaround", "prevent", "lock"]):
                                findings.append(StakeholderFinding(
                                    stakeholder_name=self.name,
                                    stakeholder_title=self.title,
                                    severity="WARNING",
                                    category="REGRESSION_RISK",
                                    issue_number=num,
                                    summary=f"Past fix detected in {rel_file} ({sha}): '{subject}'",
                                    details=f"File {rel_file} has a history of bugfixes/workarounds from commit {sha} by {author}. Modifying this file risks re-introducing prior regressions.",
                                    suggested_action=f"Verify that new changes do not undo the safeguards implemented in commit {sha}."
                                ))
                except Exception:
                    pass

        has_critical = any(f.severity == "CRITICAL" for f in findings)
        return StakeholderAuditResult(
            stakeholder_name=self.name,
            stakeholder_title=self.title,
            findings=findings,
            has_critical_blockers=has_critical,
            gaps_identified=gaps
        )


class StakeholderCouncil:
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path or Path.cwd()
        self.stakeholders: List[DomainStakeholder] = [
            StorageAndBackupStakeholder(),
            NetworkingIngressStakeholder(),
            DatabaseSchemaStakeholder(),
            ServiceIntegrationStakeholder(),
            HistoricalCodebaseStakeholder()
        ]

    def audit_backlog(
        self,
        issues: List[dict],
        fact_checks: Dict[int, IssueFactCheckResult],
        inventory: CodebaseInventory
    ) -> Dict[str, StakeholderAuditResult]:
        results: Dict[str, StakeholderAuditResult] = {}
        for stakeholder in self.stakeholders:
            res = stakeholder.audit(
                issues=issues,
                fact_checks=fact_checks,
                inventory=inventory,
                repo_path=self.repo_path
            )
            results[stakeholder.name] = res
        return results

    def synthesize_gaps(self, audit_results: Dict[str, StakeholderAuditResult]) -> List[StakeholderFinding]:
        all_findings: List[StakeholderFinding] = []
        for res in audit_results.values():
            all_findings.extend(res.findings)
        # Sort by severity: CRITICAL first, then WARNING, then INFO
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        all_findings.sort(key=lambda f: severity_order.get(f.severity, 99))
        return all_findings
