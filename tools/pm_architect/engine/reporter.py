#!/usr/bin/env python3
"""
Backlog Synthesis Report Generator for 'pm architect'.
Compiles reality fact-checking, council deliberation, dictator rulings,
dependency graphing, and proposed tickets into .pm/BACKLOG_SYNTHESIS.md.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from .fact_checker import CodebaseInventory, IssueFactCheckResult
from .council import CouncilDeliberation
from .dictator import DictatorRuling
from .graph import DependencyGraph
from .tickets import ProposedTicket


class SynthesisReporter:
    def __init__(self, repo_name: str):
        self.repo_name = repo_name

    def generate_report(
        self,
        issues: List[dict],
        inventory: CodebaseInventory,
        fact_checks: Dict[int, IssueFactCheckResult],
        deliberations: Dict[int, CouncilDeliberation],
        rulings: Dict[int, DictatorRuling],
        graph: DependencyGraph,
        proposed_tickets: List[ProposedTicket]
    ) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        total_issues = len(issues)
        shovel_ready_count = len(graph.shovel_ready_sequence)
        blocked_count = len(graph.blocked_issues)
        stories_count = len(graph.stories)
        drift_count = sum(1 for fc in fact_checks.values() if fc.overall_status in ("WARNING_DRIFT", "CONTRADICTION"))
        clean_count = sum(1 for fc in fact_checks.values() if fc.is_clean)

        # Health score calculation (0 - 100)
        # Penalties: unprioritized, missing acceptance criteria, architectural contradictions, cycles
        health_score = 100
        if total_issues > 0:
            if graph.cycles:
                health_score -= 25
            health_score -= int((drift_count / total_issues) * 20)
            unprio_count = sum(1 for i in issues if not any(l.get('name', '').startswith('priority:') for l in i.get('labels', [])))
            health_score -= int((unprio_count / total_issues) * 15)
        health_score = max(10, min(100, health_score))

        lines = [
            f"# 🏛️ Backlog Synthesis & Architectural Council Report",
            f"",
            f"- **Repository**: `{self.repo_name}`",
            f"- **Generated At**: `{timestamp}`",
            f"- **Engine**: `pm architect` v1.0.0",
            f"- **Backlog Health Score**: **{health_score}/100** {'🟢 Healthy' if health_score >= 80 else '🟡 Needs Refinement' if health_score >= 60 else '🔴 High Risk'}",
            f"",
            f"---",
            f"",
            f"## 1. Executive Summary & Inventory",
            f"",
            f"| Metric | Count | Details |",
            f"| :--- | :--- | :--- |",
            f"| **Total Open Issues** | `{total_issues}` | Tracked issues in repository backlog |",
            f"| **Parent Stories / Epics** | `{stories_count}` | Monorepo feature epics (`type:story`) |",
            f"| **Shovel-Ready Candidates** | `{shovel_ready_count}` | Unblocked leaf tasks ready for `pm ship` / `pm fleet` |",
            f"| **Blocked Tasks** | `{blocked_count}` | Tasks awaiting upstream technical prerequisites |",
            f"| **Codebase Fact-Check Clean** | `{clean_count}` | Verified zero file/service path drift |",
            f"| **Asset / Spec Drift Warnings** | `{drift_count}` | Tickets referencing missing files or spec contradictions |",
            f"| **Dependency Cycles** | `{len(graph.cycles)}` | {'None detected 🟢' if not graph.cycles else f'⚠️ {len(graph.cycles)} cycle(s) flagged'} |",
            f"| **Proposed New Tickets** | `{len(proposed_tickets)}` | Research spikes & information reconciliation tickets |",
            f"",
            f"---",
            f"",
            f"## 2. Benevolent Dictator Homelab Governance Rulings",
            f"",
            f"> The Benevolent Dictator arbitrates all persona deliberations against the User's **Four Non-Negotiable Operational Axioms** for single host `bjorn`:",
            f"> 1. **Maximum Server Uptime**: Rejects all-at-once migrations; mandates canary verification.",
            f"> 2. **Zero Tolerance for Data Loss**: Mandates verified pre-flight snapshots and rollback scripts for Actual, Vaultwarden, and Home Assistant.",
            f"> 3. **Minimal Maintenance Burden**: Vetoes complex orchestrators (k8s/nomad) in favor of simple, self-contained Docker Compose.",
            f"> 4. **Single-Server Catastrophe Risk**: Blast radius containment strictly enforced; unprivileged sockets mandated.",
            f"",
            f"### Active Arbitration Rulings:",
            f""
        ]

        # Summarize Dictator rulings
        amended = [r for r in rulings.values() if r.binding_verdict != "APPROVED"]
        if not amended:
            lines.append("No active impasses or vetoes. All open issues conform cleanly to homelab operational axioms.")
        else:
            for r in amended:
                lines.append(f"- **Issue #{r.issue_number}**: **{r.binding_verdict}**")
                lines.append(f"  - *Summary*: {r.ruling_summary}")
                for s in r.mandated_safeguards:
                    lines.append(f"  - *Safeguard*: {s}")
                for v in r.veto_reasons:
                    lines.append(f"  - *Veto*: {v}")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 3. Shovel-Ready Execution Order (`pm ship` / `pm fleet`)",
            f"",
            f"The following leaf issues have **zero open blockers** and have been prioritized by topological dependency rank and impact:",
            f"",
            f"| Rank | Issue | Priority | Unblocks Downstream | Recommended Model & Tier |",
            f"| :---: | :--- | :---: | :---: | :--- |"
        ])

        prio_order = {'priority:critical': 'Critical', 'priority:high': 'High', 'priority:medium': 'Medium', 'priority:low': 'Low'}
        for rank, num in enumerate(graph.shovel_ready_sequence, 1):
            node = graph.nodes[num]
            prio_label = next((prio_order[l.lower()] for l in node.labels if l.lower() in prio_order), 'Unspecified')
            unblocks_str = f"{len(node.blocks)} issue(s)" if node.blocks else "Leaf endpoint"
            
            # Calibrate model tier based on content
            tier = "Gemini 3.8 Flash (High Thinking)" if prio_label in ('Critical', 'High') else "Gemini 3.8 Flash (Medium Thinking)"
            lines.append(f"| **{rank}** | [#{num}: {node.title}](https://github.com/{self.repo_name}/issues/{num}) | `{prio_label}` | `{unblocks_str}` | {tier} |")

        if not graph.shovel_ready_sequence:
            lines.append("| - | *No unblocked shovel-ready issues found. Resolve prerequisite blockers below.* | - | - | - |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 4. Reality Fact-Checking & Asset Verification",
            f"",
            f"Audited all ticket descriptions against repository files, compose configurations, and architecture runbooks (`docs/`):",
            f"",
            f"| Issue | Overall Status | Verified Assets | Flags & Contradictions |",
            f"| :---: | :---: | :--- | :--- |"
        ])

        for issue in issues:
            num = issue['number']
            fc = fact_checks.get(num)
            if not fc:
                continue
            status_icon = "🟢 VERIFIED" if fc.overall_status == "VERIFIED" else "🟡 DRIFT" if fc.overall_status == "WARNING_DRIFT" else "🔵 RESEARCH" if fc.overall_status == "NEEDS_RESEARCH" else "🔴 CONTRADICTION"
            
            v_items = "<br>".join([f"• {x}" for x in fc.verified_items[:3]]) if fc.verified_items else "*None declared*"
            flags = []
            if fc.missing_assets:
                flags.extend([f"⚠️ {x}" for x in fc.missing_assets[:2]])
            if fc.unverified_assumptions:
                flags.extend([f"❓ {x}" for x in fc.unverified_assumptions[:2]])
            if fc.contradictions:
                flags.extend([f"🚫 {x}" for x in fc.contradictions[:2]])
            flags_str = "<br>".join(flags) if flags else "None (Clean)"

            lines.append(f"| [#{num}](https://github.com/{self.repo_name}/issues/{num}) | `{status_icon}` | {v_items} | {flags_str} |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 5. Story Hierarchy & Dependency Graph",
            f"",
            f"```mermaid",
            f"flowchart TD"
        ])

        # Render Mermaid flowchart
        # Add stories and child nodes
        for s_num, children in graph.stories.items():
            s_title = graph.nodes[s_num].title[:35].replace('"', "'")
            lines.append(f'    subgraph Story_{s_num} ["Story #{s_num}: {s_title}"]')
            for c_num in children:
                c_title = graph.nodes[c_num].title[:30].replace('"', "'")
                lines.append(f'        I{c_num}["#{c_num}: {c_title}"]')
            lines.append(f'    end')

        # Add edges for dependencies
        edge_count = 0
        for num, node in graph.nodes.items():
            for prereq in node.prerequisites:
                if prereq in graph.nodes:
                    lines.append(f"    I{prereq} --> I{num}")
                    edge_count += 1

        if edge_count == 0:
            lines.append("    %% No explicit dependencies linked")

        lines.extend([
            f"```",
            f"",
            f"### Blocked Issues & Required Predecessors:",
            f""
        ])

        if not graph.blocked_issues:
            lines.append("No open issues are currently blocked.")
        else:
            for num, blockers in graph.blocked_issues.items():
                blockers_str = ", ".join([f"[#{b}](https://github.com/{self.repo_name}/issues/{b})" for b in blockers])
                lines.append(f"- **Issue #{num}** ({graph.nodes[num].title}): Blocked by {blockers_str}")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 6. Proposed New Tickets (Spikes & Reconciliation)",
            f"",
            f"The Architectural Council proposes creating the following research and reconciliation tickets to prevent stalled execution:",
            f""
        ])

        if not proposed_tickets:
            lines.append("No new research spikes or reconciliation tickets required at this time.")
        else:
            for idx, pt in enumerate(proposed_tickets, 1):
                type_tag = "🔬 Research Spike" if pt.ticket_type == "SPIKE" else "📝 Information Reconciliation"
                rel_str = ", ".join([f"#{n}" for n in pt.related_issues])
                lines.extend([
                    f"### {idx}. {type_tag}: `{pt.title}`",
                    f"- **Labels**: `{', '.join(pt.labels)}`",
                    f"- **Trigger**: {pt.trigger_reason}",
                    f"- **Related Issues**: {rel_str}",
                    f"",
                    f"```markdown",
                    pt.body.strip(),
                    f"```",
                    f""
                ])

        lines.extend([
            f"---",
            f"",
            f"## 7. Recommended Next Actions for TPM / User",
            f"",
            f"1. **Execute Next Shovel-Ready Task**:",
            f"   ```bash",
            f"   pm ship #{graph.shovel_ready_sequence[0] if graph.shovel_ready_sequence else '<issue-number>'}",
            f"   ```",
            f"2. **Auto-Create Proposed Spikes** (Optional):",
            f"   ```bash",
            f"   pm architect --create-issues",
            f"   ```",
            f"3. **Update Issue Labels & Prerequisites** (Optional):",
            f"   ```bash",
            f"   pm architect --apply",
            f"   ```"
        ])

        return "\n".join(lines)
