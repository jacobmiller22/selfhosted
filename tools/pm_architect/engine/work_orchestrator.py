#!/usr/bin/env python3
"""
Autonomous Planning Interval (PI) Orchestrator Engine for 'pm work'.
Decomposes high-level visions into multi-wave execution plans, evaluates dependency DAGs,
convenes the Senior Leadership Council and Domain Stakeholders, and drives progress on GitHub.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .fact_checker import RealityFactChecker, IssueFactCheckResult, CodebaseInventory
from .council import DeliberationCouncil, CouncilDeliberation
from .dictator import BenevolentDictator, DictatorRuling
from .stakeholders import StakeholderCouncil, StakeholderAuditResult, StakeholderFinding
from .graph import DependencyEngine, DependencyGraph, IssueNode
from .tickets import TicketGenerator, ProposedTicket
from .state_manager import StateManager, GitHubProgressTracker, PlanningIntervalState, WaveState, TaskState
from .watchdog import TaskWatchdog, TaskWatchdogState, WatchdogPolicy


@dataclass
class WorkerManifest:
    issue_number: int
    title: str
    branch_name: str
    base_branch: str
    thinking_tier: str
    target_modules: List[str]
    parent_pi_story: Optional[int]
    verification_commands: List[str]
    inactivity_timeout_seconds: int
    max_execution_timeout_seconds: int
    body: str


class WorkOrchestrator:
    def __init__(
        self,
        repo: str,
        repo_path: Optional[Path] = None,
        max_workers_per_wave: int = 4,
        inactivity_timeout: Optional[int] = None,
        max_task_timeout: Optional[int] = None
    ):
        self.repo = repo
        self.repo_path = repo_path or Path.cwd()
        self.max_workers_per_wave = max_workers_per_wave

        # Initialize engines
        self.fact_checker = RealityFactChecker()
        self.council = DeliberationCouncil()
        self.dictator = BenevolentDictator()
        self.stakeholder_council = StakeholderCouncil(repo_path=self.repo_path)
        self.graph_engine = DependencyEngine()
        self.ticket_generator = TicketGenerator()
        self.state_manager = StateManager(repo_path=self.repo_path)
        self.github_tracker = GitHubProgressTracker(repo=self.repo)
        self.watchdog = TaskWatchdog(
            inactivity_override=inactivity_timeout,
            max_timeout_override=max_task_timeout
        )

    def extract_module_for_issue(self, issue: dict, inventory: CodebaseInventory) -> str:
        """Identify primary service/directory module touched by the issue."""
        title = issue.get("title", "").lower()
        body = (issue.get("body", "") or "").lower()
        combined = f"{title}\n{body}"

        # Match title scopes e.g. feat(actual), fix(vaultwarden), chore(docs)
        scope_match = re.search(r'^[a-z]+(?:\(([^)]+)\))?:', title)
        if scope_match and scope_match.group(1):
            scope = scope_match.group(1).lower()
            return scope

        # Check against mapped services
        for svc in inventory.services:
            if svc in combined:
                return svc

        # Check against common directories
        for folder in ["docs", "tools", "tests", "actual", "vaultwarden", "homeassistant", "nginx-proxy-manager"]:
            if folder in combined:
                return folder

        return "core"

    def extract_thinking_tier(self, body: str) -> str:
        """Extract recommended thinking tier from issue body."""
        if not body:
            return "Medium"
        match = re.search(r'\*\*Thinking Level\*\*:\s*([A-Za-z]+)', body, re.IGNORECASE)
        if match:
            return match.group(1).capitalize()
        # Heuristics based on complexity
        body_lower = body.lower()
        if any(w in body_lower for w in ["migration", "crypto", "encryption", "concurrency", "deadlock"]):
            return "High"
        if any(w in body_lower for w in ["doc", "typo", "readme", "comment"]):
            return "Low"
        return "Medium"

    def slugify(self, text: str) -> str:
        """Create clean branch slug from issue title."""
        clean = re.sub(r'^[a-z]+(?:\([^)]+\))?:\s*', '', text, flags=re.IGNORECASE)
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', clean).strip('-').lower()
        return slug[:40] or "task"

    def partition_into_waves(
        self,
        candidate_issues: List[dict],
        closed_numbers: Set[int],
        inventory: CodebaseInventory
    ) -> List[WaveState]:
        """
        Topologically partition issues into sequential execution waves.
        Ensures each wave contains mutually disjoint module scopes (zero Git merge conflicts).
        """
        # Map issue number to issue dict and module
        issue_map: Dict[int, dict] = {i["number"]: i for i in candidate_issues}
        issue_modules: Dict[int, str] = {
            i["number"]: self.extract_module_for_issue(i, inventory)
            for i in candidate_issues
        }

        # Build dependency graph
        graph = self.graph_engine.build_graph(candidate_issues, closed_numbers)

        remaining_numbers = set(issue_map.keys())
        completed_in_plan = set(closed_numbers)
        waves: List[WaveState] = []
        wave_id = 1

        while remaining_numbers:
            current_wave_tasks: Dict[str, TaskState] = {}
            current_wave_modules: Set[str] = set()

            # Find all issues whose prerequisites are met
            available_for_wave = []
            for num in remaining_numbers:
                node = graph.nodes.get(num)
                if not node:
                    available_for_wave.append(num)
                    continue
                # Unblocked if all prerequisites are in completed_in_plan
                if node.prerequisites.issubset(completed_in_plan):
                    available_for_wave.append(num)

            if not available_for_wave:
                # Cycle or unresolvable blocker: take first available to avoid infinite loop
                available_for_wave = [sorted(remaining_numbers)[0]]

            # Sort available by priority
            def sort_key(n):
                node = graph.nodes.get(n)
                labels = [l.lower() for l in (node.labels if node else [])]
                if "priority:critical" in labels:
                    return 0
                if "priority:high" in labels:
                    return 1
                if "priority:medium" in labels:
                    return 2
                return 3

            available_for_wave.sort(key=sort_key)

            # Select up to max_workers_per_wave with disjoint modules
            for num in available_for_wave:
                if len(current_wave_tasks) >= self.max_workers_per_wave:
                    break
                mod = issue_modules.get(num, "core")
                if mod not in current_wave_modules or mod == "core":
                    issue = issue_map[num]
                    current_wave_tasks[str(num)] = TaskState(
                        issue_number=num,
                        title=issue.get("title", ""),
                        status="pending"
                    )
                    current_wave_modules.add(mod)

            if not current_wave_tasks:
                # Fallback if module collisions prevented selection
                first_num = available_for_wave[0]
                issue = issue_map[first_num]
                current_wave_tasks[str(first_num)] = TaskState(
                    issue_number=first_num,
                    title=issue.get("title", ""),
                    status="pending"
                )
                current_wave_modules.add(issue_modules.get(first_num, "core"))

            # Register wave
            wave = WaveState(
                wave_id=wave_id,
                status="pending",
                tasks=current_wave_tasks,
                disjoint_modules=sorted(list(current_wave_modules))
            )
            waves.append(wave)

            # Mark selected issues as completed in plan for next wave unblocking
            for num_str in current_wave_tasks.keys():
                n = int(num_str)
                remaining_numbers.remove(n)
                completed_in_plan.add(n)

            wave_id += 1

        return waves

    def build_worker_manifests(
        self,
        wave: WaveState,
        all_issues: Dict[int, dict],
        base_branch: str,
        parent_pi_story: Optional[int] = None
    ) -> List[WorkerManifest]:
        """Prepare execution manifests for subagents in a wave."""
        manifests = []
        for num_str in wave.tasks.keys():
            num = int(num_str)
            issue = all_issues.get(num, {})
            title = issue.get("title", "")
            body = issue.get("body", "") or ""
            thinking_tier = self.extract_thinking_tier(body)
            slug = self.slugify(title)
            branch = f"feature/task-{num}-{slug}"

            # Extract test/verification commands if present in issue
            verify_cmds = []
            test_matches = re.findall(r'`(pnpm [^`]+|npm [^`]+|pytest[^`]*|go test[^`]*|docker compose[^`]*)`', body)
            if test_matches:
                verify_cmds = test_matches
            else:
                verify_cmds = ["pytest", "npm test"]

            mod = self.extract_module_for_issue(issue, self.fact_checker.inventory)
            policy = self.watchdog.get_policy(thinking_tier)

            manifests.append(WorkerManifest(
                issue_number=num,
                title=title,
                branch_name=branch,
                base_branch=base_branch,
                thinking_tier=thinking_tier,
                target_modules=[mod],
                parent_pi_story=parent_pi_story,
                verification_commands=verify_cmds,
                inactivity_timeout_seconds=policy.inactivity_timeout_seconds,
                max_execution_timeout_seconds=policy.max_execution_timeout_seconds,
                body=body
            ))
        return manifests

    def evaluate_task_health(
        self,
        task: TaskState,
        worktree_path: Optional[Path],
        current_time: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate task health against inactivity and execution ceiling."""
        watchdog_state = TaskWatchdogState(
            issue_number=task.issue_number,
            thinking_tier="Medium",  # Default if unspecified
            worktree_path=worktree_path,
            started_at=task.started_at or 0.0,
            last_activity_at=task.last_activity_at or task.started_at or 0.0
        )
        is_healthy, reason = self.watchdog.evaluate(watchdog_state, current_time=current_time)
        if not is_healthy:
            task.timed_out = True
            task.timeout_reason = reason
            task.status = "failed"
        return is_healthy, reason

    def prepare_planning_interval(
        self,
        pi_number: int,
        vision: str,
        open_issues: List[dict],
        closed_numbers: Set[int],
        milestone: Optional[str] = None
    ) -> Tuple[PlanningIntervalState, List[ProposedTicket]]:
        """
        Execute pre-flight audit, convene councils, generate gap tickets,
        and construct the PlanningIntervalState.
        """
        # Filter issues by milestone if specified
        candidate_issues = open_issues
        if milestone:
            candidate_issues = [
                i for i in open_issues
                if (i.get("milestone") or {}).get("title") == milestone
            ]

        # 1. Fact-checking
        fact_checks: Dict[int, IssueFactCheckResult] = {}
        for issue in candidate_issues:
            fact_checks[issue["number"]] = self.fact_checker.check_issue(issue)

        # 2. Deliberation Council & Benevolent Dictator
        deliberations: Dict[int, CouncilDeliberation] = {}
        rulings: Dict[int, DictatorRuling] = {}
        council_summaries = []

        for issue in candidate_issues:
            num = issue["number"]
            fc = fact_checks[num]
            delib = self.council.deliberate(issue, fc, self.fact_checker.inventory)
            deliberations[num] = delib
            ruling = self.dictator.arbitrate(issue, fc, delib, self.fact_checker.inventory)
            rulings[num] = ruling
            for m in ruling.mandated_safeguards:
                council_summaries.append(f"Issue #{num}: {m}")

        # 3. Domain Stakeholder Council
        stakeholder_audits = self.stakeholder_council.audit_backlog(
            issues=candidate_issues,
            fact_checks=fact_checks,
            inventory=self.fact_checker.inventory
        )
        stakeholder_gaps = self.stakeholder_council.synthesize_gaps(stakeholder_audits)
        stakeholder_summaries = []
        for g in stakeholder_gaps[:5]:
            stakeholder_summaries.append(f"[{g.stakeholder_title}] Issue #{g.issue_number}: {g.summary}")

        # 4. Generate Research & Reconciliation Tickets for gaps
        proposed_tickets = self.ticket_generator.generate_tickets(
            fact_checks=fact_checks,
            deliberations=deliberations,
            rulings=rulings,
            inventory=self.fact_checker.inventory,
            issues=candidate_issues
        )

        # 5. Partition issues into disjoint waves
        waves = self.partition_into_waves(
            candidate_issues=candidate_issues,
            closed_numbers=closed_numbers,
            inventory=self.fact_checker.inventory
        )

        state = PlanningIntervalState(
            pi_number=pi_number,
            vision=vision,
            milestone=milestone,
            phase="INCEPTION",
            current_wave_index=0,
            waves=waves,
            council_rulings_summary=council_summaries,
            stakeholder_findings_summary=stakeholder_summaries,
            completed_issues=[]
        )

        return state, proposed_tickets
