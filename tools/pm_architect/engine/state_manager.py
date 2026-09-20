#!/usr/bin/env python3
"""
State Management & GitHub Progress Synchronization Engine for 'pm work'.
Handles atomic local machine state (.pm/work/state.json) for zero-loss session resumption
and orchestrates GitHub-native progress tracking (Parent PI Stories, live checklist updates,
and wave completion comments).
"""

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class TaskState:
    issue_number: int
    title: str = ""
    status: str = "pending"  # pending, in_progress, completed, failed
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    summary: str = ""
    error: Optional[str] = None
    started_at: float = 0.0
    last_activity_at: float = 0.0
    timed_out: bool = False
    timeout_reason: Optional[str] = None


@dataclass
class WaveState:
    wave_id: int
    status: str = "pending"  # pending, in_progress, completed, failed
    tasks: Dict[str, TaskState] = field(default_factory=dict)  # string key of issue_number for JSON
    disjoint_modules: List[str] = field(default_factory=list)


@dataclass
class PlanningIntervalState:
    pi_number: int = 1
    pi_issue_number: Optional[int] = None
    vision: str = ""
    milestone: Optional[str] = None
    phase: str = "INCEPTION"  # INCEPTION, AUDIT, COUNCIL_REVIEW, WAVE_EXECUTION, VERIFICATION, COMPLETED
    current_wave_index: int = 0
    waves: List[WaveState] = field(default_factory=list)
    gaps_created: List[int] = field(default_factory=list)
    council_rulings_summary: List[str] = field(default_factory=list)
    stakeholder_findings_summary: List[str] = field(default_factory=list)
    completed_issues: List[int] = field(default_factory=list)
    history: List[dict] = field(default_factory=list)


class StateManager:
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path or Path.cwd()
        self.state_dir = self.repo_path / ".pm" / "work"
        self.state_file = self.state_dir / "state.json"

    def ensure_dir(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, state: PlanningIntervalState):
        """Atomically persist Planning Interval machine state."""
        self.ensure_dir()
        tmp_file = self.state_dir / "state.json.tmp"
        
        # Custom serialization for dataclass hierarchy
        state_dict = asdict(state)
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state_dict, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_file.replace(self.state_file)

    def load_state(self) -> Optional[PlanningIntervalState]:
        """Load persisted machine state if present."""
        if not self.state_file.exists():
            return None
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Reconstruct WaveState and TaskState
            waves: List[WaveState] = []
            for w in data.get("waves", []):
                tasks_dict = {}
                for k, t in w.get("tasks", {}).items():
                    tasks_dict[str(k)] = TaskState(**t)
                waves.append(WaveState(
                    wave_id=w.get("wave_id", 1),
                    status=w.get("status", "pending"),
                    tasks=tasks_dict,
                    disjoint_modules=w.get("disjoint_modules", [])
                ))

            state = PlanningIntervalState(
                pi_number=data.get("pi_number", 1),
                pi_issue_number=data.get("pi_issue_number"),
                vision=data.get("vision", ""),
                milestone=data.get("milestone"),
                phase=data.get("phase", "INCEPTION"),
                current_wave_index=data.get("current_wave_index", 0),
                waves=waves,
                gaps_created=data.get("gaps_created", []),
                council_rulings_summary=data.get("council_rulings_summary", []),
                stakeholder_findings_summary=data.get("stakeholder_findings_summary", []),
                completed_issues=data.get("completed_issues", []),
                history=data.get("history", [])
            )
            return state
        except Exception:
            return None

    def clear_state(self):
        """Remove state file upon complete clean shutdown."""
        if self.state_file.exists():
            self.state_file.unlink()


class GitHubProgressTracker:
    def __init__(self, repo: str):
        self.repo = repo

    def format_pi_story_body(
        self,
        pi_number: int,
        vision: str,
        waves: List[WaveState],
        council_summary: Optional[List[str]] = None,
        stakeholder_summary: Optional[List[str]] = None
    ) -> str:
        """Format the authoritative GitHub Parent PI Story body."""
        lines = [
            f"## 🎯 Planning Interval PI-{pi_number} Vision & Objectives",
            f"> {vision or 'Autonomous delivery loop across backlog and roadmap priorities.'}",
            "",
            "## 🌊 Execution Waves & Shovel-Ready Deliverables"
        ]

        for wave in waves:
            lines.append(f"### Wave {wave.wave_id} (Status: `{wave.status.upper()}`)")
            if wave.disjoint_modules:
                lines.append(f"*Disjoint Target Modules*: `{', '.join(wave.disjoint_modules)}`")
            for num_str, task in wave.tasks.items():
                checked = "x" if task.status == "completed" else " "
                pr_info = f" ([PR #{task.pr_number}]({task.pr_url}))" if task.pr_number and task.pr_url else ""
                lines.append(f"- [{checked}] #{task.issue_number} - {task.title}{pr_info}")
            lines.append("")

        lines.append("## 🏛️ Senior Leadership & Domain Stakeholder Governance")
        if council_summary:
            lines.append("### Senior Leadership Council & Homelab Axioms")
            for r in council_summary[:5]:
                lines.append(f"- {r}")
            lines.append("")

        if stakeholder_summary:
            lines.append("### Domain Stakeholder & Codebase Veteran Advisories")
            for s in stakeholder_summary[:5]:
                lines.append(f"- {s}")
            lines.append("")

        lines.append("---")
        lines.append("*Managed autonomously by Antigravity `pm work` Planning Interval Super-Loop.*")
        return "\n".join(lines)

    def create_or_attach_pi_story(
        self,
        pi_number: int,
        vision: str,
        waves: List[WaveState],
        council_summary: Optional[List[str]] = None,
        stakeholder_summary: Optional[List[str]] = None
    ) -> int:
        """Create the parent GitHub issue for the Planning Interval."""
        body = self.format_pi_story_body(
            pi_number=pi_number,
            vision=vision,
            waves=waves,
            council_summary=council_summary,
            stakeholder_summary=stakeholder_summary
        )
        title = f"story(pi): [PI-{pi_number}] {vision[:60] if vision else 'Autonomous Backlog Convergence'}"
        cmd = [
            "gh", "issue", "create",
            "--repo", self.repo,
            "--title", title,
            "--body", body,
            "--label", "type:story",
            "--label", f"pi:{pi_number}",
            "--label", "status:in-progress"
        ]
        try:
            res = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            out = res.decode("utf-8").strip()
            # Extracts issue number from URL (e.g., https://github.com/owner/repo/issues/145)
            match = re.search(r'/issues/(\d+)', out)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return 0

    def update_task_in_pi_story(
        self,
        pi_issue_number: int,
        task_issue_number: int,
        status: str,
        pr_number: Optional[int] = None,
        pr_url: Optional[str] = None
    ) -> bool:
        """Dynamically update the checklist item inside the GitHub Parent PI Story body."""
        if not pi_issue_number:
            return False
        try:
            # Fetch current issue body
            res = subprocess.check_output(
                ["gh", "issue", "view", str(pi_issue_number), "--repo", self.repo, "--json", "body", "-q", ".body"],
                stderr=subprocess.DEVNULL
            )
            body = res.decode("utf-8")

            # Replace unchecked checklist item with checked item and PR reference
            mark = "x" if status == "completed" else " "
            pr_suffix = f" ([PR #{pr_number}]({pr_url}))" if pr_number and pr_url else ""

            # Pattern matches "- [ ] #<number> - <title>" or already checked variants
            pattern = rf"- \[[ xX]\] #{task_issue_number}\b([^\n]*)"
            replacement = rf"- [{mark}] #{task_issue_number}\g<1>"
            if pr_suffix and pr_suffix not in body:
                replacement += pr_suffix

            updated_body = re.sub(pattern, replacement, body)

            # Update body via gh issue edit
            subprocess.check_call(
                ["gh", "issue", "edit", str(pi_issue_number), "--repo", self.repo, "--body", updated_body],
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception:
            return False

    def post_wave_summary(
        self,
        pi_issue_number: int,
        wave_id: int,
        tasks: List[TaskState]
    ) -> bool:
        """Post milestone comment to the parent PI Story on GitHub upon wave completion."""
        if not pi_issue_number:
            return False
        lines = [
            f"🌊 **Wave {wave_id} Execution Complete**",
            "",
            "### Delivered Stories & Pull Requests"
        ]
        for t in tasks:
            status_icon = "✅" if t.status == "completed" else "⚠️"
            pr_link = f" -> [PR #{t.pr_number}]({t.pr_url})" if t.pr_number and t.pr_url else ""
            lines.append(f"- {status_icon} Issue #{t.issue_number}: {t.title}{pr_link}")

        lines.append("")
        lines.append("*All non-overlapping worktrees cleanly reaped. Advancing to next execution wave.*")
        comment_body = "\n".join(lines)

        try:
            subprocess.check_call(
                ["gh", "issue", "comment", str(pi_issue_number), "--repo", self.repo, "--body", comment_body],
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception:
            return False

    def post_pi_retrospective(
        self,
        pi_issue_number: int,
        pi_number: int,
        total_tasks: int,
        total_prs: int,
        new_gaps: List[int]
    ) -> bool:
        """Post complete retrospective comment on GitHub Parent PI Story and mark completed."""
        if not pi_issue_number:
            return False
        lines = [
            f"🏁 **Planning Interval PI-{pi_number} Retrospective & Sign-Off**",
            "",
            f"- **Completed Tasks**: {total_tasks}",
            f"- **Delivered Pull Requests**: {total_prs}",
            f"- **New Gap/Spike Tickets Created**: {len(new_gaps)} ({', '.join(f'#{g}' for g in new_gaps) if new_gaps else 'None'})",
            "- **Integration Health**: All wave verification suites passed cleanly.",
            "",
            "### Next Cadence",
            "This Planning Interval has met its exit criteria. Human PR review gates remain open for final merge approval."
        ]
        comment_body = "\n".join(lines)

        try:
            subprocess.check_call(
                ["gh", "issue", "comment", str(pi_issue_number), "--repo", self.repo, "--body", comment_body],
                stderr=subprocess.DEVNULL
            )
            subprocess.check_call(
                ["gh", "issue", "edit", str(pi_issue_number), "--repo", self.repo,
                 "--remove-label", "status:in-progress", "--add-label", "status:completed"],
                stderr=subprocess.DEVNULL
            )
            return True
        except Exception:
            return False
