#!/usr/bin/env python3
"""
PM Autonomous Planning Interval Super-Loop CLI ('pm work').
Drives autonomous delivery across entire Planning Intervals (PIs) with multi-wave
disjoint execution, Senior Leadership & Domain Stakeholder reviews, GitHub-native
progress tracking, and zero-loss context preservation.
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
    from tools.pm_architect.engine.work_orchestrator import WorkOrchestrator, WorkerManifest
    from tools.pm_architect.engine.state_manager import StateManager, GitHubProgressTracker, PlanningIntervalState
    from tools.pm_architect.engine.fact_checker import RealityFactChecker
    from tools.pm_architect.engine.council import DeliberationCouncil
    from tools.pm_architect.engine.dictator import BenevolentDictator
    from tools.pm_architect.engine.stakeholders import StakeholderCouncil
    from tools.pm_architect.engine.graph import DependencyEngine
    from tools.pm_architect.engine.tickets import TicketGenerator
except ImportError:
    from engine.work_orchestrator import WorkOrchestrator, WorkerManifest
    from engine.state_manager import StateManager, GitHubProgressTracker, PlanningIntervalState
    from engine.fact_checker import RealityFactChecker
    from engine.council import DeliberationCouncil
    from engine.dictator import BenevolentDictator
    from engine.stakeholders import StakeholderCouncil
    from engine.graph import DependencyEngine
    from engine.tickets import TicketGenerator


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


def detect_default_branch(repo: str) -> str:
    """Detect default branch of the repository."""
    try:
        res = subprocess.check_output(
            ['gh', 'repo', 'view', repo, '--json', 'defaultBranchRef', '-q', '.defaultBranchRef.name'],
            stderr=subprocess.DEVNULL
        )
        branch = res.decode('utf-8').strip()
        if branch:
            return branch
    except Exception:
        pass
    return "main"


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


def create_gap_ticket(repo: str, ticket) -> Optional[int]:
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
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode('utf-8').strip()
        match = re.search(r'/issues/(\d+)', out)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Planning Interval (PI) Super-Loop ('pm work')"
    )
    parser.add_argument("--vision", type=str, default="",
                        help="Strategic vision or objective for this Planning Interval")
    parser.add_argument("--milestone", type=str, default=None,
                        help="Target specific milestone")
    parser.add_argument("--repo", type=str, default=None,
                        help="Explicit target repository (owner/repo)")
    parser.add_argument("--max-pis", type=int, default=1,
                        help="Maximum Planning Intervals to execute (default: 1)")
    parser.add_argument("--continuous", action="store_true",
                        help="Continuous delivery mode: cycle across PIs until backlog is complete")
    parser.add_argument("--max-workers-per-wave", type=int, default=4,
                        help="Maximum concurrent subagents per wave (default: 4)")
    parser.add_argument("--inactivity-timeout", type=int, default=None,
                        help="Inactivity / stagnation watchdog threshold in seconds (default: based on thinking tier)")
    parser.add_argument("--task-timeout", type=int, default=None,
                        help="Maximum execution timeout ceiling in seconds (default: based on thinking tier)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume in-flight Planning Interval from .pm/work/state.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Perform complete PI audit and wave plan without modifying GitHub issues")
    parser.add_argument("--auto-create-gaps", action="store_true",
                        help="Automatically create research spikes on GitHub for discovered gaps")
    parser.add_argument("--json", action="store_true",
                        help="Output state telemetry as JSON")
    args = parser.parse_args()

    repo = args.repo or detect_repository()
    if not repo:
        print("Error: Could not detect GitHub repository. Specify with --repo <owner/repo>.", file=sys.stderr)
        sys.exit(1)

    repo_path = Path.cwd()
    base_branch = detect_default_branch(repo)
    orchestrator = WorkOrchestrator(
        repo=repo,
        repo_path=repo_path,
        max_workers_per_wave=args.max_workers_per_wave,
        inactivity_timeout=args.inactivity_timeout,
        max_task_timeout=args.task_timeout
    )

    state_mgr = StateManager(repo_path=repo_path)

    # 1. Check for Resume Mode
    if args.resume:
        existing_state = state_mgr.load_state()
        if not existing_state:
            print("No in-flight Planning Interval found in .pm/work/state.json to resume.", file=sys.stderr)
            sys.exit(1)

        print("=" * 70)
        print(f" 🧭 RESUMING PLANNING INTERVAL PI-{existing_state.pi_number}")
        print("=" * 70)
        print(f"Vision: {existing_state.vision or 'Backlog Convergence'}")
        print(f"Parent PI Story: #{existing_state.pi_issue_number}")
        print(f"Current Phase: {existing_state.phase}")
        print(f"Current Wave: {existing_state.current_wave_index + 1} of {len(existing_state.waves)}")
        print()

        if args.json:
            print(json.dumps(existing_state.__dict__, indent=2, default=str))
            return

        print("Active Wave Status:")
        if existing_state.current_wave_index < len(existing_state.waves):
            w = existing_state.waves[existing_state.current_wave_index]
            print(f"  Wave {w.wave_id} (Status: {w.status}):")
            for tid, t in w.tasks.items():
                print(f"    - Task #{t.issue_number}: {t.title} [{t.status}]")
        return

    # 2. Fetch Backlog Telemetry
    try:
        open_issues, closed_numbers, open_prs = fetch_backlog(repo)
    except Exception as e:
        print(f"Error querying GitHub issues for {repo}: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter out stories that are already completed or awaiting review
    active_candidates = [
        i for i in open_issues
        if not any(l['name'].lower() in ['status:completed', 'type:story'] for l in i.get('labels', []))
    ]

    # 3. Deliberate & Construct Planning Interval Plan
    pi_state, proposed_tickets = orchestrator.prepare_planning_interval(
        pi_number=1,
        vision=args.vision,
        open_issues=active_candidates,
        closed_numbers=closed_numbers,
        milestone=args.milestone
    )

    # 4. JSON Output Mode
    if args.json:
        output = {
            "repo": repo,
            "pi_number": pi_state.pi_number,
            "vision": pi_state.vision,
            "waves_count": len(pi_state.waves),
            "total_tasks": sum(len(w.tasks) for w in pi_state.waves),
            "waves": [
                {
                    "wave_id": w.wave_id,
                    "disjoint_modules": w.disjoint_modules,
                    "tasks": [
                        {"number": t.issue_number, "title": t.title, "status": t.status}
                        for t in w.tasks.values()
                    ]
                }
                for w in pi_state.waves
            ],
            "stakeholder_gaps_count": len(pi_state.stakeholder_findings_summary),
            "proposed_tickets_count": len(proposed_tickets)
        }
        print(json.dumps(output, indent=2))
        return

    # 5. CLI Presentation & Execution
    print("=" * 70)
    print(f" 🚀 PM WORK: PLANNING INTERVAL PI-{pi_state.pi_number} EXECUTION MANIFEST")
    print(f" Repository: {repo} | Base Branch: {base_branch}")
    print("=" * 70)
    print(f"Vision / Milestone: {pi_state.vision or 'Backlog & Roadmap Convergence'}\n")

    print("🏛️  SENIOR LEADERSHIP & STAKEHOLDER DELIBERATION")
    print("-" * 70)
    if pi_state.stakeholder_findings_summary:
        print("Domain Stakeholder Findings:")
        for s in pi_state.stakeholder_findings_summary[:4]:
            print(f"  • {s}")
    if pi_state.council_rulings_summary:
        print("Council Mandated Safeguards:")
        for c in pi_state.council_rulings_summary[:4]:
            print(f"  • {c}")
    print()

    print(f"🌊 EXECUTION SCHEDULE: {len(pi_state.waves)} WAVES ({sum(len(w.tasks) for w in pi_state.waves)} TOTAL TASKS)")
    print("-" * 70)
    for wave in pi_state.waves:
        print(f"Wave {wave.wave_id}: {len(wave.tasks)} parallel subagent tasks | Modules: {', '.join(wave.disjoint_modules)}")
        manifests = orchestrator.build_worker_manifests(wave, {i["number"]: i for i in active_candidates}, base_branch)
        for m in manifests:
            print(f"  - Issue #{m.issue_number}: {m.title}")
            print(f"    Branch: {m.branch_name} | Thinking: {m.thinking_tier} | Scope: {m.target_modules}")
        print()

    if proposed_tickets:
        print(f"💡 PROPOSED RESEARCH SPIKES & RECONCILIATIONS ({len(proposed_tickets)})")
        print("-" * 70)
        for pt in proposed_tickets:
            print(f"  - [{pt.ticket_type}] {pt.title}")
        print()

    # If Dry Run, stop here
    if args.dry_run:
        print("🔍 DRY RUN COMPLETE: No GitHub issues created or modified.")
        return

    # 6. Live Execution: Auto-Create Gaps & Parent PI Story on GitHub
    if args.auto_create_gaps and proposed_tickets:
        print("Creating proposed gap tickets on GitHub...")
        for pt in proposed_tickets:
            created_num = create_gap_ticket(repo, pt)
            if created_num:
                print(f"  ✓ Created Issue #{created_num}: {pt.title}")
                pi_state.gaps_created.append(created_num)

    # Create Parent PI Story on GitHub
    print("\nCreating Parent PI Story on GitHub...")
    pi_story_num = orchestrator.github_tracker.create_or_attach_pi_story(
        pi_number=pi_state.pi_number,
        vision=pi_state.vision,
        waves=pi_state.waves,
        council_summary=pi_state.council_rulings_summary,
        stakeholder_summary=pi_state.stakeholder_findings_summary
    )
    pi_state.pi_issue_number = pi_story_num
    pi_state.phase = "WAVE_EXECUTION"

    if pi_story_num:
        print(f"  ✓ Created Parent PI Story: https://github.com/{repo}/issues/{pi_story_num}")
    else:
        print("  ⚠️ Notice: Running locally without online issue creation.")

    # Persist Machine State
    state_mgr.save_state(pi_state)
    print(f"  ✓ Saved machine state to .pm/work/state.json")
    print("\n✅ Ready for Wave 1 Dispatch via Antigravity 'invoke_subagent'.")


if __name__ == "__main__":
    main()
