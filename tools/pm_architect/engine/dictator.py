#!/usr/bin/env python3
"""
Benevolent Dictator / Tie-Breaker Protocol for Backlog Synthesis.
Arbitrates debate impasses and enforces the User's 4 Non-Negotiable Operational Axioms:
1. Maximum Server Uptime (Host 'bjorn' safety)
2. Zero Tolerance for Data Loss (Pre-flight backups & atomic rollback plans)
3. Minimal Maintenance Burden ("Set-and-forget", veto fragile over-engineering)
4. Single-Server Catastrophe Risk (Blast radius containment, no HA cluster exists)
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .fact_checker import IssueFactCheckResult, CodebaseInventory
from .council import CouncilDeliberation


@dataclass
class DictatorRuling:
    issue_number: int
    binding_verdict: str  # APPROVED, AMENDED_WITH_CONSTRAINTS, VETOED
    primary_axiom_invoked: Optional[str] = None
    ruling_summary: str = ""
    mandated_safeguards: List[str] = field(default_factory=list)
    veto_reasons: List[str] = field(default_factory=list)


class BenevolentDictator:
    AXIOM_1_UPTIME = "Axiom 1: Maximum Server Uptime ('bjorn' must remain online; reject all-at-once migrations)"
    AXIOM_2_ZERO_DATA_LOSS = "Axiom 2: Zero Tolerance for Data Loss (Databases require verified backups & atomic rollback)"
    AXIOM_3_LOW_MAINTENANCE = "Axiom 3: Minimal Maintenance Burden ('Set-and-forget'; veto fragile over-engineering)"
    AXIOM_4_SINGLE_SERVER = "Axiom 4: Single-Server Catastrophe Risk (No HA cluster exists; blast radius must be contained)"

    def arbitrate(
        self,
        issue: dict,
        fact_check: IssueFactCheckResult,
        deliberation: CouncilDeliberation,
        inventory: CodebaseInventory
    ) -> DictatorRuling:
        """Arbitrate council impasses or formulate binding operational rulings."""
        issue_number = issue.get('number', 0)
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        combined = f"{title}\n{body}".lower()

        mandated_safeguards: List[str] = []
        veto_reasons: List[str] = []
        primary_axiom: Optional[str] = None

        # --- Check Axiom 4: Single-Server Catastrophe Risk ---
        if "docker.sock" in combined or "privileged: true" in combined or "host network" in combined:
            primary_axiom = self.AXIOM_4_SINGLE_SERVER
            mandated_safeguards.append(
                "CONTAINMENT MANDATE: bjorn is a single standalone host with no standby failover. "
                "Any container requiring docker.sock must use read-only socket mount (:ro) or scoped socket-proxy."
            )

        # --- Check Axiom 2: Zero Tolerance for Data Loss ---
        modifies_storage = any(db in combined for db in ['actual', 'vaultwarden', 'homeassistant', 'sqlite', 'database', 'postgres', 'couchdb'])
        if modifies_storage:
            if not any(k in combined for k in ['backup', 'snapshot', 'rollback', 'read-only']):
                primary_axiom = primary_axiom or self.AXIOM_2_ZERO_DATA_LOSS
                mandated_safeguards.append(
                    "DATA LOSS SAFEGUARD: Pre-flight verified backup and tested atomic rollback script "
                    "MUST be executed prior to applying storage or schema changes."
                )

        # --- Check Axiom 1: Maximum Server Uptime ---
        is_risky_migration = any(k in combined for k in ['cutover', 'all-at-once', 'downtime', 'rip and replace', 'monolithic rewrite'])
        if is_risky_migration:
            primary_axiom = primary_axiom or self.AXIOM_1_UPTIME
            mandated_safeguards.append(
                "UPTIME MANDATE: All migrations must execute in canary or parallel side-by-side mode. "
                "Immediate cutover without verified staging validation is forbidden."
            )

        # Ignore tooling / architect self-maintenance issues from infrastructure vetoes
        is_tooling = any(t in title.lower() for t in ['fix(architect)', 'feat(architect)', 'chore(architect)', 'tools/pm_architect', 'pm architect'])

        # --- Check Axiom 3: Minimal Maintenance Burden ---
        is_overengineered = not is_tooling and bool(
            re.search(r'\b(?:kubernetes|k8s|consul|nomad|zookeeper|distributed consensus)\b', combined)
        )
        if is_overengineered:
            veto_reasons.append(
                "VETOED UNDER AXIOM 3: Heavy multi-node orchestration is strictly vetoed on single host bjorn. "
                "The user requires a low-maintenance, 'set-and-forget' stack using Docker Compose."
            )

        # Determine binding verdict
        if veto_reasons:
            binding_verdict = "VETOED"
            ruling_summary = f"The Benevolent Dictator has vetoed this issue under {self.AXIOM_3_LOW_MAINTENANCE}."
        elif mandated_safeguards or deliberation.has_impasse:
            binding_verdict = "AMENDED_WITH_CONSTRAINTS"
            ruling_summary = (
                f"The Benevolent Dictator intervened under {primary_axiom or self.AXIOM_4_SINGLE_SERVER}. "
                f"Mandating {len(mandated_safeguards)} strict operational safeguard(s) to protect host 'bjorn'."
            )
        else:
            binding_verdict = "APPROVED"
            ruling_summary = "Architectural design aligns cleanly with all four Homelab Operational Axioms."

        return DictatorRuling(
            issue_number=issue_number,
            binding_verdict=binding_verdict,
            primary_axiom_invoked=primary_axiom,
            ruling_summary=ruling_summary,
            mandated_safeguards=mandated_safeguards,
            veto_reasons=veto_reasons
        )
