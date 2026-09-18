#!/usr/bin/env python3
"""
Research Spike & Information Reconciliation Ticket Generator for Backlog Synthesis.
Automatically creates proposals for:
1. Knowledge Gap Spikes (type:research) for unverified assumptions or unproven APIs.
2. Information Reconciliation Tickets (type:reconciliation / docs) for conflicting specs.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .fact_checker import IssueFactCheckResult, CodebaseInventory
from .council import CouncilDeliberation
from .dictator import DictatorRuling


@dataclass
class ProposedTicket:
    ticket_type: str  # SPIKE or RECONCILIATION
    title: str
    labels: List[str] = field(default_factory=list)
    body: str = ""
    related_issues: List[int] = field(default_factory=list)
    trigger_reason: str = ""


class TicketGenerator:
    def __init__(self):
        pass

    def generate_tickets(
        self,
        fact_checks: Dict[int, IssueFactCheckResult],
        deliberations: Dict[int, CouncilDeliberation],
        rulings: Dict[int, DictatorRuling],
        inventory: CodebaseInventory
    ) -> List[ProposedTicket]:
        """Generate structured ticket proposals for knowledge gaps and documentation drift."""
        proposed: List[ProposedTicket] = []
        seen_spike_topics = set()
        seen_reconciliation_topics = set()

        # 1. Inspect Fact-Check Results for Contradictions (Reconciliation Tickets)
        for num, fc in fact_checks.items():
            for contra in fc.contradictions:
                topic_key = contra[:60]
                if topic_key in seen_reconciliation_topics:
                    continue
                seen_reconciliation_topics.add(topic_key)

                ticket = ProposedTicket(
                    ticket_type="RECONCILIATION",
                    title=f"chore(docs): Reconcile architecture specification for Issue #{num}",
                    labels=["type:reconciliation", "documentation", "priority:high"],
                    related_issues=[num],
                    trigger_reason=contra,
                    body=(
                        f"## Information Reconciliation Required\n\n"
                        f"### Trigger\n"
                        f"During automated backlog fact-checking, a contradiction was identified in Issue #{num}:\n"
                        f"> {contra}\n\n"
                        f"### Problem Statement\n"
                        f"The codebase or documentation state differs from the proposed implementation plan. "
                        f"To avoid implementing against stale or conflicting architectural assumptions, "
                        f"we must reconcile the authoritative documentation.\n\n"
                        f"### Deliverables\n"
                        f"- [ ] Audit authoritative docs (`docs/BACKUP_ARCHITECTURE.md`, `docs/RESTORE.md`) vs live configs.\n"
                        f"- [ ] Update documentation or issue specifications to align on single source of truth.\n"
                        f"- [ ] Unblock Issue #{num} with verified architectural directives.\n\n"
                        f"### Related Issues\n"
                        f"- Discovered while reviewing: #{num}\n"
                    )
                )
                proposed.append(ticket)

        # 2. Inspect Unverified Assumptions & Research Needs (Spike Tickets)
        for num, fc in fact_checks.items():
            for assumption in fc.unverified_assumptions:
                topic_key = assumption[:50]
                if topic_key in seen_spike_topics:
                    continue
                seen_spike_topics.add(topic_key)

                ticket = ProposedTicket(
                    ticket_type="SPIKE",
                    title=f"spike(research): Investigate assumption for Issue #{num} ({topic_key})",
                    labels=["type:research", "priority:medium"],
                    related_issues=[num],
                    trigger_reason=assumption,
                    body=(
                        f"## Technical Research Spike (`type:research`)\n\n"
                        f"### Context & Gap Analysis\n"
                        f"Issue #{num} contains an unverified technical assumption:\n"
                        f"> \"{assumption}\"\n\n"
                        f"To ensure execution velocity and eliminate downstream agent failures during `pm ship`, "
                        f"this dedicated research spike will prove or disprove the hypothesis.\n\n"
                        f"### Spike Objectives\n"
                        f"- [ ] Benchmark or verify expected runtime behavior / API contract in isolation.\n"
                        f"- [ ] Document findings and concrete constraints in `docs/` or issue comments.\n"
                        f"- [ ] Transition Issue #{num} acceptance criteria from assumption to verified specification.\n\n"
                        f"### Related Issues\n"
                        f"- Prerequisites for: #{num}\n"
                    )
                )
                proposed.append(ticket)

        # 3. Inspect Dictator Mandates requiring Spike / Prototyping
        for num, ruling in rulings.items():
            if ruling.binding_verdict == "AMENDED_WITH_CONSTRAINTS":
                for safeguard in ruling.mandated_safeguards:
                    if "CONTAINMENT MANDATE" in safeguard:
                        topic_key = f"containment_socket_{num}"
                        if topic_key not in seen_spike_topics:
                            seen_spike_topics.add(topic_key)
                            proposed.append(ProposedTicket(
                                ticket_type="SPIKE",
                                title=f"spike(security): Validate unprivileged socket proxy for Issue #{num}",
                                labels=["type:research", "priority:high", "security"],
                                related_issues=[num],
                                trigger_reason=safeguard,
                                body=(
                                    f"## Security Containment Spike\n\n"
                                    f"### Dictator Mandate\n"
                                    f"{safeguard}\n\n"
                                    f"### Objectives\n"
                                    f"- [ ] Prototype scoped docker socket proxy (e.g. Tecnativa docker-socket-proxy) with read-only permissions.\n"
                                    f"- [ ] Verify target container functions without full root `docker.sock` mount.\n"
                                    f"- [ ] Update Issue #{num} compose deliverable with hardened socket configuration.\n"
                                )
                            ))

        return proposed
