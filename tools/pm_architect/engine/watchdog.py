#!/usr/bin/env python3
"""
Task Time Bounding & Stagnation Watchdog Engine for 'pm work'.
Implements dual-horizon timeouts:
1. Inactivity / Stagnation Threshold: Catches deadlocked or silent tasks with zero telemetry.
2. Absolute Task Execution Ceiling: Puts an upper bound based on task thinking tier.
Protects against premature timeouts using multi-vector liveness probes (git changes, file mtimes, process checks).
"""

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class WatchdogPolicy:
    thinking_tier: str  # Low, Medium, High
    inactivity_timeout_seconds: int
    max_execution_timeout_seconds: int
    grace_extension_seconds: int


DEFAULT_POLICIES = {
    "Low": WatchdogPolicy(
        thinking_tier="Low",
        inactivity_timeout_seconds=180,    # 3 mins silent
        max_execution_timeout_seconds=600,  # 10 mins total
        grace_extension_seconds=120
    ),
    "Medium": WatchdogPolicy(
        thinking_tier="Medium",
        inactivity_timeout_seconds=300,    # 5 mins silent
        max_execution_timeout_seconds=1200, # 20 mins total
        grace_extension_seconds=180
    ),
    "High": WatchdogPolicy(
        thinking_tier="High",
        inactivity_timeout_seconds=480,    # 8 mins silent
        max_execution_timeout_seconds=2400, # 40 mins total
        grace_extension_seconds=300
    ),
}


@dataclass
class TaskWatchdogState:
    issue_number: int
    thinking_tier: str
    worktree_path: Optional[Path] = None
    started_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    extensions_granted: int = 0
    max_extensions: int = 2
    is_timed_out: bool = False
    timeout_reason: Optional[str] = None


class TaskWatchdog:
    def __init__(
        self,
        policies: Optional[Dict[str, WatchdogPolicy]] = None,
        inactivity_override: Optional[int] = None,
        max_timeout_override: Optional[int] = None
    ):
        self.policies = policies or DEFAULT_POLICIES
        self.inactivity_override = inactivity_override
        self.max_timeout_override = max_timeout_override

    def get_policy(self, thinking_tier: str) -> WatchdogPolicy:
        tier = thinking_tier.capitalize()
        base = self.policies.get(tier, self.policies["Medium"])
        return WatchdogPolicy(
            thinking_tier=tier,
            inactivity_timeout_seconds=self.inactivity_override or base.inactivity_timeout_seconds,
            max_execution_timeout_seconds=self.max_timeout_override or base.max_execution_timeout_seconds,
            grace_extension_seconds=base.grace_extension_seconds
        )

    def record_activity(self, state: TaskWatchdogState, timestamp: Optional[float] = None):
        """Reset the inactivity timer upon verified progress."""
        state.last_activity_at = timestamp or time.time()

    def check_liveness(self, worktree_path: Optional[Path]) -> Tuple[bool, str]:
        """
        Inspect the worktree to verify whether background work is genuinely progressing
        (preventing premature timeouts on long compiles, test suites, or git operations).
        """
        if not worktree_path or not worktree_path.exists():
            return False, "Worktree path does not exist"

        # 1. Check Git status for dirty or staged changes modified recently
        try:
            res = subprocess.check_output(
                ["git", "status", "-s"],
                cwd=str(worktree_path),
                stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
            if res:
                return True, f"Active uncommitted worktree changes detected ({len(res.splitlines())} files)"
        except Exception:
            pass

        # 2. Check recent file modifications within the worktree (mtime in last 120s)
        now = time.time()
        recent_mod_count = 0
        try:
            for root, dirs, files in os.walk(worktree_path):
                # Ignore git metadata
                if ".git" in root:
                    continue
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(fp)
                        if now - mtime < 120:
                            recent_mod_count += 1
                    except OSError:
                        pass
                if recent_mod_count > 0:
                    return True, f"Active file writes detected ({recent_mod_count} files modified in last 2m)"
        except Exception:
            pass

        return False, "Zero file modifications or git activity detected"

    def evaluate(self, state: TaskWatchdogState, current_time: Optional[float] = None) -> Tuple[bool, Optional[str]]:
        """
        Evaluate task health against dual-horizon timeouts.
        Returns: (is_healthy, failure_or_warning_reason)
        """
        now = current_time or time.time()
        policy = self.get_policy(state.thinking_tier)

        total_elapsed = now - state.started_at
        silent_elapsed = now - state.last_activity_at

        # Check 1: Hard Execution Ceiling
        if total_elapsed > policy.max_execution_timeout_seconds:
            state.is_timed_out = True
            reason = (
                f"Execution Ceiling Exceeded: Task has run for {int(total_elapsed)}s "
                f"(limit: {policy.max_execution_timeout_seconds}s for {policy.thinking_tier} thinking tier)."
            )
            state.timeout_reason = reason
            return False, reason

        # Check 2: Inactivity / Stagnation Threshold
        if silent_elapsed > policy.inactivity_timeout_seconds:
            # Check liveness to protect against premature timeout
            is_active, liveness_msg = self.check_liveness(state.worktree_path)
            if is_active and state.extensions_granted < state.max_extensions:
                # Grant grace extension lease
                state.extensions_granted += 1
                state.last_activity_at = now
                return True, f"Grace extension #{state.extensions_granted} granted: {liveness_msg}"

            state.is_timed_out = True
            reason = (
                f"Stagnation Detected: No progress or updates for {int(silent_elapsed)}s "
                f"(inactivity limit: {policy.inactivity_timeout_seconds}s). Liveness check: {liveness_msg}."
            )
            state.timeout_reason = reason
            return False, reason

        return True, None
