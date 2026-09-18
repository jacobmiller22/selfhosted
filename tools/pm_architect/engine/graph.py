#!/usr/bin/env python3
"""
Comprehensive Dependency Linking Engine & Story Hierarchy Graph for Backlog Synthesis.
Extracts explicit and implicit dependencies, parent story groupings, cycle detection,
and topological sorting for shovel-ready execution sequencing.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class IssueNode:
    number: int
    title: str
    labels: List[str] = field(default_factory=list)
    is_story: bool = False
    parent_story: Optional[int] = None
    prerequisites: Set[int] = field(default_factory=set)  # Issues that must complete before this issue
    blocks: Set[int] = field(default_factory=set)          # Issues that this issue blocks
    is_shovel_ready: bool = False
    blocking_reasons: List[str] = field(default_factory=list)


@dataclass
class DependencyGraph:
    nodes: Dict[int, IssueNode] = field(default_factory=dict)
    stories: Dict[int, List[int]] = field(default_factory=dict)  # story_number -> [child_issue_numbers]
    cycles: List[List[int]] = field(default_factory=list)
    shovel_ready_sequence: List[int] = field(default_factory=list)
    blocked_issues: Dict[int, List[int]] = field(default_factory=dict)  # issue_number -> [open_blockers]


class DependencyEngine:
    def __init__(self):
        pass

    def extract_dependencies_from_text(self, text: str) -> Tuple[Set[int], Set[int], Optional[int]]:
        """
        Extract prerequisites, blocked issues, and parent story from issue text.
        Returns: (prerequisites, blocks, parent_story)
        """
        prereqs = set()
        blocks = set()
        parent_story = None

        # Prerequisites / Blocked by: #<N>
        prereq_matches = re.findall(
            r'(?:blocked by:?|depends on:?|prerequisites?:?|requires:?)\s*(?:issues?:?\s*)?#?(\d+)',
            text,
            re.IGNORECASE
        )
        for m in prereq_matches:
            prereqs.add(int(m))

        # Blocks: #<N>
        blocks_matches = re.findall(
            r'(?:blocks:?|prerequisite for:?)\s*(?:issues?:?\s*)?#?(\d+)',
            text,
            re.IGNORECASE
        )
        for m in blocks_matches:
            blocks.add(int(m))

        # Parent Story / Epic: Part of Story #<N> or Story: #<N>
        parent_matches = re.findall(
            r'(?:part of|story|parent|epic)\s*(?:story|epic|issue)?:?\s*#(\d+)',
            text,
            re.IGNORECASE
        )
        if parent_matches:
            parent_story = int(parent_matches[0])

        return prereqs, blocks, parent_story

    def infer_domain_dependencies(self, issue: dict, all_issues: Dict[int, dict]) -> Set[int]:
        """
        Infer implicit technical dependencies based on architectural domain hierarchy.
        E.g., Alerting requires monitoring; S3 replication requires backup runner.
        """
        inferred = set()
        title = issue.get('title', '').lower()
        body = (issue.get('body', '') or '').lower()
        combined = f"{title}\n{body}"

        # 1. Alerting depends on monitoring metrics deployment
        if "feat(alerting)" in title:
            for num, other in all_issues.items():
                if num == issue.get('number'):
                    continue
                other_title = other.get('title', '').lower()
                if "deploy victoriametrics" in other_title or "deploy host and container telemetry" in other_title:
                    inferred.add(num)

        # 2. Grafana dashboards depend on VictoriaMetrics
        if "grafana" in title and not "deploy victoriametrics" in title:
            for num, other in all_issues.items():
                if "victoriametrics" in other.get('title', '').lower() and "deploy" in other.get('title', '').lower():
                    inferred.add(num)

        # 3. Scheduled failover & ephemeral staging require cold-storage restore runbook or multi-db verification
        if "scheduled failover" in title or "ephemeral staging" in title:
            for num, other in all_issues.items():
                other_title = other.get('title', '').lower()
                if "reusable backup-template" in other_title or "standardize actual budget & vaultwarden" in other_title:
                    inferred.add(num)

        # 4. Monorepo PR preview deployments depend on Wildcard SSL and Coolify webhook
        if "feat(compose): pr preview" in title or "pr preview environments" in title:
            for num, other in all_issues.items():
                other_title = other.get('title', '').lower()
                if "npm wildcard" in other_title or "configure coolify pr automation" in other_title:
                    inferred.add(num)

        return inferred

    def build_graph(self, open_issues: List[dict], closed_numbers: Optional[Set[int]] = None) -> DependencyGraph:
        """Construct the complete dependency graph and hierarchy from open issues."""
        closed_set = closed_numbers or set()
        graph = DependencyGraph()
        issues_by_num = {i['number']: i for i in open_issues}

        # 1. Initialize nodes
        for issue in open_issues:
            num = issue['number']
            title = issue.get('title', '')
            labels = [l.get('name', '') for l in issue.get('labels', [])]
            is_story = 'type:story' in [l.lower() for l in labels] or title.lower().startswith('story')

            prereqs, blocks, parent_story = self.extract_dependencies_from_text(issue.get('body', '') or '')
            
            # Infer domain dependencies if not already stated
            inferred = self.infer_domain_dependencies(issue, issues_by_num)
            prereqs.update(inferred)

            node = IssueNode(
                number=num,
                title=title,
                labels=labels,
                is_story=is_story,
                parent_story=parent_story,
                prerequisites=prereqs,
                blocks=blocks
            )
            graph.nodes[num] = node

            if is_story:
                if num not in graph.stories:
                    graph.stories[num] = []

        # 2. Bidirectional linking & parent story aggregation
        for num, node in graph.nodes.items():
            # Link prerequisites into blocks
            for p in list(node.prerequisites):
                if p in graph.nodes:
                    graph.nodes[p].blocks.add(num)

            # Link blocks into prerequisites
            for b in list(node.blocks):
                if b in graph.nodes:
                    graph.nodes[b].prerequisites.add(num)

            # Map into parent stories
            if node.parent_story and node.parent_story in graph.stories:
                if num not in graph.stories[node.parent_story]:
                    graph.stories[node.parent_story].append(num)

        # 3. Detect Cycles (Tarjan's or simple DFS)
        visited = {}  # 0: unvisited, 1: visiting, 2: visited
        cycles = []

        def dfs_cycle(current: int, path: List[int]):
            visited[current] = 1
            for neighbor in graph.nodes[current].prerequisites:
                if neighbor not in graph.nodes:
                    continue
                if visited.get(neighbor, 0) == 1:
                    cycle_slice = path[path.index(neighbor):] + [neighbor]
                    cycles.append(cycle_slice)
                elif visited.get(neighbor, 0) == 0:
                    dfs_cycle(neighbor, path + [neighbor])
            visited[current] = 2

        for num in graph.nodes:
            if visited.get(num, 0) == 0:
                dfs_cycle(num, [num])
        graph.cycles = cycles

        # 4. Identify Shovel-Ready vs Blocked Nodes
        for num, node in graph.nodes.items():
            # Filter open blockers (exclude closed issues and nonexistent issues)
            open_blockers = [p for p in node.prerequisites if p in graph.nodes and p not in closed_set]
            labels_lower = [l.lower() for l in node.labels]

            if node.is_story:
                # Stories are containers, not leaf tasks
                node.is_shovel_ready = False
                node.blocking_reasons.append("Parent epic / story container")
            elif 'status:in-progress' in labels_lower:
                node.is_shovel_ready = False
                node.blocking_reasons.append("Currently in-progress")
            elif 'status:completed' in labels_lower:
                node.is_shovel_ready = False
                node.blocking_reasons.append("Completed (PR open awaiting merge)")
            elif open_blockers:
                node.is_shovel_ready = False
                node.blocking_reasons.append(f"Blocked by open issues: {open_blockers}")
                graph.blocked_issues[num] = open_blockers
            else:
                node.is_shovel_ready = True

        # 5. Calculate Topological Shovel-Ready Sequence
        # Rank shovel-ready tasks by priority tier and in-degree
        prio_order = {
            'priority:critical': 0,
            'priority:high': 1,
            'priority:medium': 2,
            'priority:low': 3
        }
        
        shovel_ready_nodes = [n for n in graph.nodes.values() if n.is_shovel_ready]
        
        def sort_key(n: IssueNode):
            prio_rank = 99
            for l in n.labels:
                l_lower = l.lower()
                if l_lower in prio_order:
                    prio_rank = min(prio_rank, prio_order[l_lower])
            # Secondary key: how many downstream tasks this unblocks (descending)
            downstream_count = len(n.blocks)
            return (prio_rank, -downstream_count, n.number)

        shovel_ready_nodes.sort(key=sort_key)
        graph.shovel_ready_sequence = [n.number for n in shovel_ready_nodes]

        return graph
