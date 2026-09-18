#!/usr/bin/env python3
"""
Reality Fact-Checking Engine for Backlog Synthesis.
Inspects local repository assets (files, docker-compose services, ports, env vars, docs)
and validates issue claims, referenced paths, and architecture alignment.
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ServiceInfo:
    name: str
    compose_file: str
    ports: List[str] = field(default_factory=list)
    volumes: List[str] = field(default_factory=list)
    environment: List[str] = field(default_factory=list)
    image: Optional[str] = None
    restart: Optional[str] = None


@dataclass
class CodebaseInventory:
    repo_root: Path
    files: Set[str] = field(default_factory=set)
    directories: Set[str] = field(default_factory=set)
    compose_files: Dict[str, dict] = field(default_factory=dict)
    services: Dict[str, ServiceInfo] = field(default_factory=dict)
    ports_mapped: Dict[str, str] = field(default_factory=dict)  # port -> service
    env_vars: Set[str] = field(default_factory=set)
    doc_files: Dict[str, str] = field(default_factory=dict)


@dataclass
class FactCheckFinding:
    entity_type: str  # file, service, port, volume, env_var, doc_drift, assumption
    name: str
    status: str  # VERIFIED, MISSING, DRIFT, CONTRADICTION, UNVERIFIED_ASSUMPTION
    details: str
    context: str = ""


@dataclass
class IssueFactCheckResult:
    issue_number: int
    title: str
    overall_status: str  # VERIFIED, WARNING_DRIFT, CONTRADICTION, NEEDS_RESEARCH
    findings: List[FactCheckFinding] = field(default_factory=list)
    verified_items: List[str] = field(default_factory=list)
    missing_assets: List[str] = field(default_factory=list)
    unverified_assumptions: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.overall_status == "VERIFIED"


class RealityFactChecker:
    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = Path(repo_root or os.getcwd()).resolve()
        self.inventory = self.build_inventory()

    def build_inventory(self) -> CodebaseInventory:
        """Scan repository files, compose configurations, ports, and documentation."""
        inventory = CodebaseInventory(repo_root=self.repo_root)

        # 1. Scan filesystem for all tracked / non-hidden files
        for root, dirs, filenames in os.walk(self.repo_root):
            # Prune hidden directories and virtualenvs
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.venv')]
            rel_dir = os.path.relpath(root, self.repo_root)
            if rel_dir != ".":
                inventory.directories.add(rel_dir)

            for f in filenames:
                if f.startswith('.'):
                    continue
                rel_path = os.path.relpath(os.path.join(root, f), self.repo_root)
                inventory.files.add(rel_path)

        # 2. Inspect Docker Compose files
        compose_patterns = ['compose.yml', 'docker-compose.yml', 'compose.yaml', 'docker-compose.yaml']
        for file_path in inventory.files:
            if any(file_path.endswith(p) for p in compose_patterns):
                abs_path = self.repo_root / file_path
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f) or {}
                    inventory.compose_files[file_path] = data
                    
                    services = data.get('services', {}) or {}
                    for sname, sdata in services.items():
                        if not isinstance(sdata, dict):
                            continue
                        
                        ports = []
                        for p in sdata.get('ports', []) or []:
                            port_str = str(p)
                            ports.append(port_str)
                            # Extract host port if mapped
                            if ':' in port_str:
                                host_port = port_str.split(':')[0].strip().split('/')[-1]
                                inventory.ports_mapped[host_port] = f"{sname} ({file_path})"

                        volumes = [str(v) for v in (sdata.get('volumes', []) or [])]
                        
                        env_list = []
                        raw_env = sdata.get('environment', []) or []
                        if isinstance(raw_env, dict):
                            for k in raw_env.keys():
                                env_list.append(str(k))
                                inventory.env_vars.add(str(k))
                        elif isinstance(raw_env, list):
                            for item in raw_env:
                                k = str(item).split('=')[0]
                                env_list.append(k)
                                inventory.env_vars.add(k)

                        sinfo = ServiceInfo(
                            name=sname,
                            compose_file=file_path,
                            ports=ports,
                            volumes=volumes,
                            environment=env_list,
                            image=sdata.get('image'),
                            restart=sdata.get('restart')
                        )
                        inventory.services[sname] = sinfo
                except Exception:
                    pass

        # 3. Read documentation files
        for f in inventory.files:
            if f.startswith('docs/') and f.endswith('.md'):
                abs_p = self.repo_root / f
                try:
                    with open(abs_p, 'r', encoding='utf-8') as df:
                        inventory.doc_files[f] = df.read()
                except Exception:
                    pass

        return inventory

    KNOWN_EXTENSIONS = {
        '.md', '.yml', '.yaml', '.sh', '.py', '.ts', '.js', '.json',
        '.sql', '.env', '.txt', '.conf', '.toml', '.onnx', '.sqlite',
        '.sqlite3', '.db', '.pem', '.key', '.crt', '.html', '.css',
        '.dockerfile', '.template'
    }

    NON_PATH_TOKENS = {
        'http://', 'https://', 'github.com', 'gh ', 'git ', 'wt ',
        'curl ', 'docker ', 'sqlite3 ', 'python', 'pnpm ', 'npm ',
        'origin/', 'feature/', 'fix/', '<', '>', '{', '}', '$', '*',
        ':latest', 'gcr.io', 'docker.io', 'ghcr.io'
    }

    RUNTIME_DATA_PATTERNS = {
        'db.sqlite3', 'account.sqlite', 'database.sqlite', 'home-assistant_v2.db',
        'rsa_key.pem', 'keys.json', 'coolify.sql', 'prometheus.yml'
    }

    def is_valid_candidate_path(self, p: str) -> bool:
        """Filter out non-paths (English terms with slashes, URLs, flags, volume mounts)."""
        p = p.strip().strip('\'\"`.,;:()[]{}')
        if not p:
            return False
        if any(tok in p for tok in self.NON_PATH_TOKENS):
            return False
        if ' ' in p or '=' in p or '\n' in p:
            return False
        if re.match(r'^\d+/\d+$', p):  # e.g. 80/443, 24/7, 2/3
            return False
        if re.match(r'^[A-Z0-9_\-]+/[A-Z0-9_\-]+$', p) and not any(p.endswith(ext) for ext in self.KNOWN_EXTENSIONS):
            # Acronym pairs like S3/B2, I/O, CPU/RAM, RTO/RPO, UID/GID, WAL/RSA
            return False
        if re.search(r':\w+$', p):  # Docker volume mounts :ro, :rw
            return False
        if p.endswith(('/s', '/min', '/h', '/d')):  # Units kB/s, bytes/s
            return False
        if p.startswith(('jacobmiller22/', 'coolify.', 'gemini/', '.gemini/', 'downloads/', 'Downloads/')) or p.startswith('~/'):
            return False

        has_ext = any(p.endswith(ext) for ext in self.KNOWN_EXTENSIONS)
        top_dirs = {d.split('/')[0] for d in self.inventory.directories} | {'.pm', '.github'}
        parts = p.lstrip('./').split('/')
        first_part = parts[0]
        starts_top_dir = first_part in top_dirs

        if has_ext:
            return True
        if starts_top_dir and len(parts) > 1:
            return True
        return False

    def extract_potential_paths(self, text: str) -> Set[str]:
        """Extract valid path-like strings from markdown or issue body."""
        candidates = set()
        # Find backtick strings: `path/to/file` or `command path/to/file`
        backticks = re.findall(r'`([^`\n]+)`', text)
        for b in backticks:
            b = b.strip()
            tokens = b.split()
            for tok in tokens:
                tok = tok.strip('\'\"`.,;:()[]{}')
                if self.is_valid_candidate_path(tok):
                    candidates.add(tok.lstrip('./'))

        # Find raw markdown paths: e.g. docs/RESTORE.md or actual/compose.yml
        raw_paths = re.findall(r'\b([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\./]+)\b', text)
        for p in raw_paths:
            p = p.strip('.,;:()[]{}')
            if self.is_valid_candidate_path(p):
                candidates.add(p.lstrip('./'))

        return candidates

    def is_deliverable_or_runtime_asset(self, path: str, combined_text: str) -> bool:
        """Check if path is a planned deliverable in the issue or runtime data asset."""
        basename = Path(path).name
        if basename in self.RUNTIME_DATA_PATTERNS or path.startswith(('tmp/', 'staging/', 'vw-stage-data/')):
            return True

        escaped = re.escape(path)

        # 1. If explicitly marked as modifying or removing an existing file, it must exist
        if re.search(rf'\b(?:modify|update|edit|refactor|patch|delete|remove)\b[^.\n]*?{escaped}', combined_text, re.IGNORECASE):
            return False

        # 2. Check for action verbs or checklist items on the same line
        pattern = rf'(?:\[NEW\]|create|author|implement|add|new\s+file|deliverables?:?|introduce|write|provision|scaffold|generate|\[\s*[\sx]\s*\])[^.\n]*?{escaped}'
        if re.search(pattern, combined_text, re.IGNORECASE):
            return True

        pattern_rev = rf'{escaped}[^.\n]*?(?:will\s+be\s+created|created|implemented|added|as\s+a\s+deliverable)'
        if re.search(pattern_rev, combined_text, re.IGNORECASE):
            return True

        # 3. Check if under a Deliverables / Scope / Tasks / Acceptance Criteria section
        lines = combined_text.split('\n')
        in_deliverables_section = False
        for line in lines:
            line_strip = line.strip()
            if re.match(r'^#+\s*(?:deliverables?|scope|tasks?|acceptance criteria|artifacts|key requirements|deliverable)', line_strip, re.IGNORECASE):
                in_deliverables_section = True
                continue
            elif re.match(r'^#+\s*', line_strip):
                in_deliverables_section = False
                continue
            if in_deliverables_section and (path in line or basename in line):
                return True

        # 4. Check if in issue title for feat/docs
        first_line = lines[0] if lines else ''
        if re.match(r'^(?:feat|docs|chore|spike)\b', first_line, re.IGNORECASE) and (path in first_line or basename in first_line):
            return True

        return False

    def extract_services_mentioned(self, text: str) -> Set[str]:
        """Extract service names mentioned in issue body."""
        found = set()
        for sname in self.inventory.services.keys():
            pattern = rf'\b{re.escape(sname)}\b'
            if re.search(pattern, text, re.IGNORECASE):
                found.add(sname)
        return found

    def check_issue(self, issue: dict) -> IssueFactCheckResult:
        """Fact-check an individual issue against the codebase inventory."""
        issue_number = issue.get('number', 0)
        title = issue.get('title', '')
        body = issue.get('body', '') or ''
        combined_text = f"{title}\n{body}"

        findings: List[FactCheckFinding] = []
        verified_items: List[str] = []
        missing_assets: List[str] = []
        unverified_assumptions: List[str] = []
        contradictions: List[str] = []

        # 1. Fact-check referenced file paths
        paths = self.extract_potential_paths(combined_text)
        for path in paths:
            exists = (path in self.inventory.files or 
                      path in self.inventory.directories or 
                      (self.repo_root / path).exists() or
                      (self.repo_root / f".{path}").exists())

            is_planned_new = self.is_deliverable_or_runtime_asset(path, combined_text)

            if exists:
                findings.append(FactCheckFinding(
                    entity_type="file",
                    name=path,
                    status="VERIFIED",
                    details=f"Asset exists at '{path}' in repository."
                ))
                verified_items.append(f"File: {path}")
            elif is_planned_new:
                findings.append(FactCheckFinding(
                    entity_type="file",
                    name=path,
                    status="VERIFIED",
                    details=f"Planned deliverable or container runtime asset: '{path}'."
                ))
                verified_items.append(f"Planned deliverable: {path}")
            else:
                findings.append(FactCheckFinding(
                    entity_type="file",
                    name=path,
                    status="MISSING",
                    details=f"Referenced path '{path}' does not exist in repository."
                ))
                missing_assets.append(f"Missing path: {path}")

        # 2. Fact-check Docker Compose Services
        services_mentioned = self.extract_services_mentioned(combined_text)
        for sname in services_mentioned:
            sinfo = self.inventory.services.get(sname)
            if sinfo:
                findings.append(FactCheckFinding(
                    entity_type="service",
                    name=sname,
                    status="VERIFIED",
                    details=f"Service '{sname}' verified in '{sinfo.compose_file}' with ports {sinfo.ports}."
                ))
                verified_items.append(f"Service: {sname} ({sinfo.compose_file})")

        # 3. Check for specific architectural contradictions
        # Example: Referencing direct rclone or manual S3 upload when docs mandate backup-runner & OpenSSL
        if re.search(r'\brclone\s+copy\b', combined_text, re.IGNORECASE) and not re.search(r'backup-runner|backup-template', combined_text, re.IGNORECASE):
            contradiction_msg = "Issue references direct raw rclone invocation instead of standard backup-runner / OpenSSL pipeline defined in docs/BACKUP_ARCHITECTURE.md."
            findings.append(FactCheckFinding(
                entity_type="doc_drift",
                name="docs/BACKUP_ARCHITECTURE.md",
                status="CONTRADICTION",
                details=contradiction_msg
            ))
            contradictions.append(contradiction_msg)

        # 4. Check for unverified assumptions and knowledge gaps
        assumption_patterns = [
            (r'assume[sd]?\s+(?:that\s+)?([^.\n]+)', "Assumption flagged"),
            (r'untested\s+([^.\n]+)', "Untested mechanism flagged"),
            (r'investigate\s+(?:whether|if)\s+([^.\n]+)', "Investigation needed"),
            (r'(?:spike|poc|proof\s+of\s+concept)\s+needed\s+(?:for\s+)?([^.\n]+)', "Research spike needed"),
            (r'to\s+be\s+determined|tbd', "Unresolved TBD parameter")
        ]
        for pattern, label in assumption_patterns:
            matches = re.finditer(pattern, combined_text, re.IGNORECASE)
            for m in matches:
                snippet = m.group(0).strip()
                findings.append(FactCheckFinding(
                    entity_type="assumption",
                    name=snippet[:50],
                    status="UNVERIFIED_ASSUMPTION",
                    details=f"{label}: '{snippet}'"
                ))
                unverified_assumptions.append(snippet)

        # Determine overall status
        if contradictions:
            overall_status = "CONTRADICTION"
        elif missing_assets:
            overall_status = "WARNING_DRIFT"
        elif unverified_assumptions:
            overall_status = "NEEDS_RESEARCH"
        else:
            overall_status = "VERIFIED"

        return IssueFactCheckResult(
            issue_number=issue_number,
            title=title,
            overall_status=overall_status,
            findings=findings,
            verified_items=verified_items,
            missing_assets=missing_assets,
            unverified_assumptions=unverified_assumptions,
            contradictions=contradictions
        )

    def batch_check_issues(self, issues: List[dict]) -> Dict[int, IssueFactCheckResult]:
        """Run fact-checking across all provided issues."""
        results = {}
        for issue in issues:
            res = self.check_issue(issue)
            results[issue['number']] = res
        return results
