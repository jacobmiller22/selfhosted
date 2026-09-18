#!/usr/bin/env python3
"""
Multi-Agent Deliberation Council for Backlog Synthesis.
Spawns and evaluates five distinct senior personas:
1. Senior Systems & Infrastructure Architect
2. Senior Software & Integration Engineer
3. Security & Data Integrity Specialist
4. Site Reliability Engineer (SRE)
5. Pragmatic Senior TPM
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .fact_checker import IssueFactCheckResult, CodebaseInventory


@dataclass
class PersonaReview:
    persona_title: str
    verdict: str  # APPROVE, REQUEST_CHANGES, FLAG_RISK, SPLIT_STORY
    rationale: str
    risks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class CouncilDeliberation:
    issue_number: int
    reviews: Dict[str, PersonaReview] = field(default_factory=dict)
    has_impasse: bool = False
    impasse_reason: str = ""
    consensus_verdict: str = "PENDING"  # CONSENSUS_APPROVED, REQUIRES_ARBITRATION, REJECTED, NEEDS_REFINEMENT


class Persona:
    def __init__(self, name: str, title: str, focus: str, core_concerns: List[str]):
        self.name = name
        self.title = title
        self.focus = focus
        self.core_concerns = core_concerns

    def evaluate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> PersonaReview:
        raise NotImplementedError


class SystemsArchitect(Persona):
    def __init__(self):
        super().__init__(
            name="systems_architect",
            title="Senior Systems & Infrastructure Architect",
            focus="Linux host internals, network topology, container runtimes, Coolify, volume persistence",
            core_concerns=[
                "Host resource limits and socket/port collisions",
                "Clean bind-mount and persistent volume paths",
                "Ingress routing consistency (NPM, Coolify, Traefik)",
                "Safe daemon and systemd process management"
            ]
        )

    def evaluate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> PersonaReview:
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        combined = f"{title}\n{body}".lower()

        risks = []
        recommendations = []

        # Check for port collisions or unbound ports
        for port in inventory.ports_mapped:
            if f":{port}" in combined or f"port {port}" in combined:
                service = inventory.ports_mapped[port]
                risks.append(f"Referenced port {port} is already claimed by {service}.")

        # Check for staging / preview container isolation
        if "staging" in combined or "preview" in combined:
            if "port" in combined and not ("ephemeral" in combined or "dynamic" in combined or "wildcard" in combined):
                risks.append("Staging deployment may conflict with production port allocations if ports are statically bound.")
                recommendations.append("Enforce dynamic host port assignment or path-based ingress via NPM wildcard.")

        # Check Coolify integration
        if "coolify" in combined:
            if "nested variable" in combined or "${{" in combined:
                risks.append("Coolify compose parser fails on nested variable substitutions (see commit 3ecda2f).")
                recommendations.append("Ensure compose templates avoid double-brace or nested env variable syntax.")

        verdict = "APPROVE"
        if risks:
            verdict = "FLAG_RISK" if len(risks) == 1 else "REQUEST_CHANGES"

        rationale = (
            f"Evaluated system topology and host impact. "
            f"{'Found potential host infrastructure risks.' if risks else 'Host infrastructure and runtime topology look sound.'}"
        )

        return PersonaReview(
            persona_title=self.title,
            verdict=verdict,
            rationale=rationale,
            risks=risks,
            recommendations=recommendations
        )


class SoftwareEngineer(Persona):
    def __init__(self):
        super().__init__(
            name="software_engineer",
            title="Senior Software & Integration Engineer",
            focus="Modular architecture, clean API contracts, idiomatic Python/TypeScript, test harnesses",
            core_concerns=[
                "Modularity and clean separation of concerns",
                "Explicit error handling and structured outputs",
                "Automated test harness and CI verifiability",
                "Prevention of code duplication and script sprawl"
            ]
        )

    def evaluate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> PersonaReview:
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        combined = f"{title}\n{body}".lower()

        risks = []
        recommendations = []

        # Missing test criteria
        has_tests = any(k in combined for k in ['test', 'pytest', 'unittest', 'verification plan', 'acceptance criteria'])
        if not has_tests:
            risks.append("No automated test plan or concrete verification command specified.")
            recommendations.append("Add explicit test commands (e.g. pytest or unit verification) to acceptance criteria.")

        # Large monolithic stories
        if len(body) > 3500 and "story" in title.lower():
            risks.append("Story scope appears overly broad with high cognitive load.")
            recommendations.append("Decompose monolithic story into discrete, testable sub-tasks.")

        verdict = "APPROVE"
        if len(risks) > 1:
            verdict = "REQUEST_CHANGES"
        elif risks:
            verdict = "FLAG_RISK"

        rationale = "Code design evaluated for modularity, maintainability, and testability."
        return PersonaReview(
            persona_title=self.title,
            verdict=verdict,
            rationale=rationale,
            risks=risks,
            recommendations=recommendations
        )


class SecuritySpecialist(Persona):
    def __init__(self):
        super().__init__(
            name="security_specialist",
            title="Security & Data Integrity Specialist",
            focus="Encryption standards, secret isolation, least-privilege permissions, zero data loss",
            core_concerns=[
                "Zero exposure of API keys, tokens, or master passwords in git",
                "Strong encryption in transit and at rest (AES-256-CBC, OpenSSL, TLS)",
                "Pre-modification atomic database backups (Actual, Vaultwarden, Home Assistant)",
                "Non-root container execution and container privilege restriction"
            ]
        )

    def evaluate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> PersonaReview:
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        combined = f"{title}\n{body}".lower()

        risks = []
        recommendations = []

        # Check database modification safety
        touches_db = any(k in combined for k in ['actual', 'vaultwarden', 'homeassistant', 'sqlite', 'database', 'postgres', 'couchdb'])
        if touches_db and not any(k in combined for k in ['backup', 'rollback', 'snapshot', 'read-only']):
            risks.append("Task modifies or integrates with persistent database without explicit snapshot or backup rollback requirement.")
            recommendations.append("Mandate pre-flight backup snapshot and verified rollback verification step.")

        # Check secret handling
        if any(k in combined for k in ['password', 'secret', 'token', 'access_key', 'api_key']):
            if not any(k in combined for k in ['env', 'vault', 'secret file', 'gitignore', 'coolify secret']):
                risks.append("Secret tokens or credentials referenced without explicit isolation mechanism.")
                recommendations.append("Enforce environment variable injection and verify .gitignore protection.")

        verdict = "APPROVE"
        if risks:
            verdict = "FLAG_RISK"

        rationale = "Security posture, encryption integrity, and data safety evaluated."
        return PersonaReview(
            persona_title=self.title,
            verdict=verdict,
            rationale=rationale,
            risks=risks,
            recommendations=recommendations
        )


class SiteReliabilityEngineer(Persona):
    def __init__(self):
        super().__init__(
            name="sre",
            title="Site Reliability Engineer (SRE)",
            focus="Failure blast radius, health check probes, telemetry, crash-loop recovery, service uptime",
            core_concerns=[
                "Contained blast radius preventing host or peer service degradation",
                "Automated health checks (docker healthcheck, http endpoints)",
                "Self-healing crash recovery and restart policies",
                "Proactive alerting on disk, memory, or backup failures"
            ]
        )

    def evaluate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> PersonaReview:
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        combined = f"{title}\n{body}".lower()

        risks = []
        recommendations = []

        # Check blast radius on single server
        if any(k in combined for k in ['docker.sock', 'host network', 'privileged: true', 'reboot', 'kernel']):
            risks.append("Task requests elevated host privileges (docker.sock or host network) which increases blast radius on single server bjorn.")
            recommendations.append("Restrict container access to unprivileged sockets or scoped proxy networks.")

        # Check monitoring / alerting awareness
        if "deploy" in combined or "provision" in combined:
            if not any(k in combined for k in ['healthcheck', 'probe', 'monitor', 'alert', 'restart']):
                risks.append("Service deployment lacks declared healthcheck probe or restart policy.")
                recommendations.append("Include Docker healthcheck and restart: unless-stopped in compose deliverable.")

        verdict = "APPROVE"
        if risks:
            verdict = "FLAG_RISK"

        rationale = "SRE review focused on service uptime, blast radius containment, and telemetry."
        return PersonaReview(
            persona_title=self.title,
            verdict=verdict,
            rationale=rationale,
            risks=risks,
            recommendations=recommendations
        )


class SeniorTPM(Persona):
    def __init__(self):
        super().__init__(
            name="tpm",
            title="Pragmatic Senior TPM",
            focus="Scope boundaries, eliminating bikeshedding, dependency sequencing, shovel-readiness",
            core_concerns=[
                "Shovel-readiness and clear acceptance criteria checkboxes",
                "Strict scope boundary enforcement and anti-bikeshedding",
                "Explicit prerequisite and blocking issue declarations",
                "Right-sized deliverables executable in a single agent session"
            ]
        )

    def evaluate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> PersonaReview:
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        labels = [l.get('name', '').lower() for l in issue.get('labels', [])]

        risks = []
        recommendations = []

        # Priority label governance
        has_prio = any(l.startswith('priority:') for l in labels)
        if not has_prio:
            risks.append("Issue is missing mandatory 'priority:*' label.")
            recommendations.append("Assign appropriate priority tier (critical, high, medium, low).")

        # Shovel-readiness checklist
        has_checkboxes = bool(re.search(r'\[[ xX]\]', body))
        if not has_checkboxes:
            risks.append("Issue lacks explicit acceptance criteria checkboxes [ ].")
            recommendations.append("Add structured acceptance criteria checklist.")

        # Missing dependency statements for complex features
        if any(k in title.lower() for k in ['deploy', 'failover', 'staging', 'alerting', 'dashboard']):
            if not any(k in body.lower() for k in ['prerequisite', 'depends on', 'blocked by']):
                risks.append("Complex infrastructure task does not declare explicit dependency links.")
                recommendations.append("Declare explicit 'Prerequisites: #<N>' linking to underlying stack foundations.")

        verdict = "APPROVE"
        if len(risks) >= 2:
            verdict = "REQUEST_CHANGES"
        elif risks:
            verdict = "FLAG_RISK"

        rationale = "TPM review of delivery velocity, scope hygiene, and dependency sequencing."
        return PersonaReview(
            persona_title=self.title,
            verdict=verdict,
            rationale=rationale,
            risks=risks,
            recommendations=recommendations
        )


class DeliberationCouncil:
    def __init__(self):
        self.personas: List[Persona] = [
            SystemsArchitect(),
            SoftwareEngineer(),
            SecuritySpecialist(),
            SiteReliabilityEngineer(),
            SeniorTPM()
        ]

    def deliberate(self, issue: dict, fact_check: IssueFactCheckResult, inventory: CodebaseInventory) -> CouncilDeliberation:
        """Run all 5 persona reviews and identify consensus or impasses."""
        reviews: Dict[str, PersonaReview] = {}
        request_changes_count = 0
        flag_risk_count = 0

        for p in self.personas:
            review = p.evaluate(issue, fact_check, inventory)
            reviews[p.name] = review
            if review.verdict == "REQUEST_CHANGES":
                request_changes_count += 1
            elif review.verdict == "FLAG_RISK":
                flag_risk_count += 1

        # Check for impasse or conflicting architectural debate
        # Example: Systems Architect requests changes on port/host while TPM wants immediate velocity
        # Or Security requests full pre-flight backup while Engineer wants light prototype
        has_impasse = False
        impasse_reason = ""

        if fact_check.contradictions:
            has_impasse = True
            impasse_reason = f"Fact-checking detected architectural contradiction: {fact_check.contradictions[0]}"
        elif request_changes_count >= 2:
            has_impasse = True
            impasse_reason = f"Council split with {request_changes_count} personas demanding changes on architectural integrity."
        elif flag_risk_count >= 3:
            has_impasse = True
            impasse_reason = f"Multiple operational risks flagged across systems, security, and reliability."

        if has_impasse:
            consensus_verdict = "REQUIRES_ARBITRATION"
        elif request_changes_count > 0:
            consensus_verdict = "NEEDS_REFINEMENT"
        else:
            consensus_verdict = "CONSENSUS_APPROVED"

        return CouncilDeliberation(
            issue_number=issue.get('number', 0),
            reviews=reviews,
            has_impasse=has_impasse,
            impasse_reason=impasse_reason,
            consensus_verdict=consensus_verdict
        )
