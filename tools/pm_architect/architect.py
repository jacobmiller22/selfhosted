#!/usr/bin/env python3
"""
PM Architectural Council & Reality Fact-Checking Engine CLI ('pm architect').
Synthesizes project backlogs, fact-checks references against real code,
runs multi-agent deliberation with Benevolent Dictator arbitration,
and produces .pm/BACKLOG_SYNTHESIS.md.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Enable running both as standalone script and repository module
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))
sys.path.insert(0, str(current_dir.parent.parent))

try:
    from tools.pm_architect.engine.fact_checker import RealityFactChecker, CodebaseInventory
    from tools.pm_architect.engine.council import DeliberationCouncil
    from tools.pm_architect.engine.dictator import BenevolentDictator
    from tools.pm_architect.engine.graph import DependencyEngine
    from tools.pm_architect.engine.tickets import TicketGenerator
    from tools.pm_architect.engine.reporter import SynthesisReporter
except ImportError:
    from engine.fact_checker import RealityFactChecker, CodebaseInventory
    from engine.council import DeliberationCouncil
    from engine.dictator import BenevolentDictator
    from engine.graph import DependencyEngine
    from engine.tickets import TicketGenerator
    from engine.reporter import SynthesisReporter


def detect_repository() -> Optional[str]:
    """Auto-detect current GitHub repository."""
    try:
        res = subprocess.check_output(
            ['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'],
            stderr=subprocess.DEVNULL
        )
        repo = res.decode('utf-8').strip()
        if repo:
            return repo
    except Exception:
        pass

    try:
        res = subprocess.check_output(
            ['git', 'remote', 'get-url', 'origin'],
            stderr=subprocess.DEVNULL
        )
        url = res.decode('utf-8').strip()
        match = re.search(r'github\.com[:/]([^/]+/[^/.]+)(?:\.git)?', url)
        if match:
            return match.group(1)
    except Exception:
        pass

    return None


def fetch_backlog(repo: str) -> Tuple[List[dict], Set[int], List[dict]]:
    """Fetch open issues, closed issue numbers, and open PRs."""
    open_issues_raw = subprocess.check_output(
        ['gh', 'issue', 'list', '--repo', repo, '--state', 'open', '--limit', '100',
         '--json', 'number,title,labels,body,milestone,assignees']
    )
    open_issues = json.loads(open_issues_raw.decode('utf-8'))

    closed_raw = subprocess.check_output(
        ['gh', 'issue', 'list', '--repo', repo, '--state', 'closed', '--limit', '100',
         '--json', 'number']
    )
    closed_numbers = set(i['number'] for i in json.loads(closed_raw.decode('utf-8')))

    prs_raw = subprocess.check_output(
        ['gh', 'pr', 'list', '--repo', repo, '--state', 'open', '--limit', '50',
         '--json', 'number,title,headRefName,url']
    )
    open_prs = json.loads(prs_raw.decode('utf-8'))

    return open_issues, closed_numbers, open_prs


def create_proposed_issue(repo: str, ticket) -> Optional[int]:
    """Create a proposed research spike or reconciliation issue on GitHub."""
    cmd = [
        'gh', 'issue', 'create',
        '--repo', repo,
        '--title', ticket.title,
        '--body', ticket.body
    ]
    for label in ticket.labels:
        cmd.extend(['--label', label])

    try:
        res = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        url = res.decode('utf-8').strip()
        match = re.search(r'/issues/(\d+)', url)
        if match:
            return int(match.group(1))
    except Exception as e:
        print(f"Warning: Failed to create issue '{ticket.title}': {e}", file=sys.stderr)
    return None


def main():
    parser = argparse.ArgumentParser(
        description="PM Architectural Council, Fact-Checking Engine & Backlog Synthesis ('pm architect')"
    )
    parser.add_argument("--repo", default=None, help="Target GitHub repository (owner/repo).")
    parser.add_argument("--output", default=".pm/BACKLOG_SYNTHESIS.md", help="Output file for synthesis report.")
    parser.add_argument("--json", action="store_true", help="Output telemetry as JSON to stdout.")
    parser.add_argument("--dry-run", action="store_true", help="Run analysis without creating output files or issues.")
    parser.add_argument("--create-issues", action="store_true", help="Automatically create proposed spike/reconciliation issues on GitHub.")
    parser.add_argument("--verbose", action="store_true", help="Print verbose execution telemetry.")

    args = parser.parse_args()

    repo = args.repo or detect_repository()
    if not repo:
        print("Error: Could not detect GitHub repository. Specify with --repo <owner/repo>.", file=sys.stderr)
        sys.exit(1)

    print(f"🏛️ Initializing PM Architectural Council for '{repo}'...")

    # 1. Fetch live backlog
    try:
        open_issues, closed_numbers, open_prs = fetch_backlog(repo)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching issues via gh CLI: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"   Loaded {len(open_issues)} open issue(s) and {len(open_prs)} open PR(s).")

    # 2. Fact-Check against Codebase
    print("🔍 Executing Reality Fact-Checking across repository assets...")
    fact_checker = RealityFactChecker()
    fact_checks = fact_checker.batch_check_issues(open_issues)

    # 3. Deliberation Council Review
    print("👥 Convening 5-Persona Deliberation Council...")
    council = DeliberationCouncil()
    deliberations = {
        i['number']: council.deliberate(i, fact_checks[i['number']], fact_checker.inventory)
        for i in open_issues
    }

    # 4. Benevolent Dictator Homelab Governance
    print("⚖️ Applying Benevolent Dictator Homelab Axioms & Arbitration...")
    dictator = BenevolentDictator()
    rulings = {
        i['number']: dictator.arbitrate(i, fact_checks[i['number']], deliberations[i['number']], fact_checker.inventory)
        for i in open_issues
    }

    # 5. Dependency Graphing & Sequencing
    print("🔗 Building Dependency Graph & Story Hierarchy...")
    dep_engine = DependencyEngine()
    graph = dep_engine.build_graph(open_issues, closed_numbers)

    # 6. Generate Research Spikes & Reconciliation Tickets
    print("🔬 Detecting Knowledge Gaps & Proposing Spike Tickets...")
    ticket_gen = TicketGenerator()
    proposed_tickets = ticket_gen.generate_tickets(
        fact_checks, deliberations, rulings, fact_checker.inventory, open_issues
    )

    # 7. Generate Synthesis Report
    reporter = SynthesisReporter(repo_name=repo)
    report_md = reporter.generate_report(
        issues=open_issues,
        inventory=fact_checker.inventory,
        fact_checks=fact_checks,
        deliberations=deliberations,
        rulings=rulings,
        graph=graph,
        proposed_tickets=proposed_tickets
    )

    # Handle Output
    if not args.dry_run and args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(report_md)
        print(f"✅ Synthesis report written to '{args.output}'")

    if args.create_issues and proposed_tickets:
        print(f"🚀 Creating {len(proposed_tickets)} proposed issue(s) on GitHub...")
        for pt in proposed_tickets:
            created_num = create_proposed_issue(repo, pt)
            if created_num:
                print(f"   Created Issue #{created_num}: {pt.title}")

    if args.json:
        payload = {
            "repository": repo,
            "total_open_issues": len(open_issues),
            "shovel_ready_count": len(graph.shovel_ready_sequence),
            "shovel_ready_sequence": graph.shovel_ready_sequence,
            "blocked_count": len(graph.blocked_issues),
            "stories_count": len(graph.stories),
            "cycles": graph.cycles,
            "proposed_tickets_count": len(proposed_tickets)
        }
        print(json.dumps(payload, indent=2))
        return

    # Print Terminal Executive Summary
    print("\n" + "=" * 60)
    print(f" BACKLOG SYNTHESIS SUMMARY: {repo}")
    print("=" * 60)
    print(f" Shovel-Ready Issues : {len(graph.shovel_ready_sequence)}")
    print(f" Blocked Issues      : {len(graph.blocked_issues)}")
    print(f" Parent Stories      : {len(graph.stories)}")
    print(f" Proposed Spikes     : {len(proposed_tickets)}")
    print(f" Dependency Cycles   : {len(graph.cycles)}")
    print("=" * 60)
    if graph.shovel_ready_sequence:
        print("\n⚡ Top Shovel-Ready Sequence for Immediate Execution:")
        for rank, num in enumerate(graph.shovel_ready_sequence[:5], 1):
            node = graph.nodes[num]
            print(f"  [{rank}] Issue #{num}: {node.title}")
            print(f"      Unblocks: {list(node.blocks) if node.blocks else 'Leaf'}")
            print(f"      Run: pm ship #{num}\n")
    print("=" * 60)


if __name__ == "__main__":
    main()
