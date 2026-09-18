#!/usr/bin/env python3
"""
Unit tests validating CI/CD Coolify deployment pipeline runbook and README.md integration.
Verifies document presence, required sections, architectural diagrams, commands,
and link integrity.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestCiCdPipelineDocs(unittest.TestCase):
    def test_ci_cd_runbook_exists(self):
        doc_path = REPO_ROOT / "docs" / "CI_CD_COOLIFY_PIPELINE.md"
        self.assertTrue(doc_path.exists(), "docs/CI_CD_COOLIFY_PIPELINE.md must exist")

    def test_ci_cd_runbook_contains_core_architecture_and_diagrams(self):
        doc_path = REPO_ROOT / "docs" / "CI_CD_COOLIFY_PIPELINE.md"
        content = doc_path.read_text(encoding="utf-8")

        # Ingress pipeline and ports
        self.assertIn("Nginx Proxy Manager", content)
        self.assertIn("Coolify", content)
        self.assertIn("Traefik", content)
        self.assertIn("Port 443", content)
        self.assertIn("Port 8080", content)
        self.assertIn("Port 50080", content)
        self.assertIn("bjorn", content)

        # Mermaid sequence diagram
        self.assertIn("sequenceDiagram", content)
        self.assertIn("pr-N-service.preview.cloud", content)

        # Division of responsibility
        self.assertIn("Division of Responsibility", content)
        self.assertIn("Outer Ingress", content)
        self.assertIn("Inner Service Mesh", content)

    def test_ci_cd_runbook_contains_service_onboarding(self):
        doc_path = REPO_ROOT / "docs" / "CI_CD_COOLIFY_PIPELINE.md"
        content = doc_path.read_text(encoding="utf-8")

        self.assertIn("New Service Onboarding Guide", content)
        self.assertIn("compose.yml", content)
        self.assertIn("watch_paths", content)
        self.assertIn("preview.cloud.jacobmiller22.com", content)

    def test_ci_cd_runbook_contains_troubleshooting_and_security(self):
        doc_path = REPO_ROOT / "docs" / "CI_CD_COOLIFY_PIPELINE.md"
        content = doc_path.read_text(encoding="utf-8")

        # GitHub settings & logs
        self.assertIn("Recent Deliveries", content)
        self.assertIn("ssh bjorn \"docker logs --tail 100 coolify\"", content)
        self.assertIn("application_deployments", content)
        self.assertIn("502 Bad Gateway", content)
        self.assertIn("404 Not Found", content)

        # Security & HMAC
        self.assertIn("X-Hub-Signature-256", content)
        self.assertIn("HMAC-SHA256", content)
        self.assertIn("Rotation Runbook", content)
        self.assertIn("openssl rand -hex 32", content)

    def test_readme_contains_runbooks_table_and_link(self):
        readme_path = REPO_ROOT / "README.md"
        self.assertTrue(readme_path.exists(), "README.md must exist in repo root")

        content = readme_path.read_text(encoding="utf-8")
        self.assertIn("docs/CI_CD_COOLIFY_PIPELINE.md", content)
        self.assertIn("Architecture & Operational Runbooks", content)
        self.assertIn("docs/INFRASTRUCTURE_TOPOLOGY.md", content)
        self.assertIn("docs/BACKUP_ARCHITECTURE.md", content)
        self.assertIn("docs/RESTORE.md", content)
        self.assertIn("docs/MONITORING_ARCHITECTURE.md", content)

    def test_markdown_relative_links_in_readme(self):
        readme_path = REPO_ROOT / "README.md"
        content = readme_path.read_text(encoding="utf-8")

        import re
        links = re.findall(r'\[.*?\]\((docs/[^)#]+)\)', content)
        for link in links:
            target = REPO_ROOT / link
            self.assertTrue(target.exists(), f"Target file '{link}' in README.md does not exist")


if __name__ == "__main__":
    unittest.main()
