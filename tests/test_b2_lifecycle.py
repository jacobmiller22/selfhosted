#!/usr/bin/env python3
"""
Unit tests verifying Backblaze B2 server-side bucket lifecycle policy architecture,
least-privilege credential security guarantees, and elimination of client-side deletion routines.
"""

import json
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_ARCH_DOC = REPO_ROOT / "docs" / "BACKUP_ARCHITECTURE.md"
RUNNER_README = REPO_ROOT / "tools" / "backup-runner" / "README.md"
BACKUP_ENGINE = REPO_ROOT / "tools" / "backup-runner" / "backup-engine.sh"
ENTRYPOINT = REPO_ROOT / "tools" / "backup-runner" / "entrypoint.sh"


class TestB2LifecycleArchitecture(unittest.TestCase):
    def test_backup_engine_excludes_client_side_pruning(self):
        """Ensure backup-engine.sh contains no client-side deletion commands or functions."""
        content = BACKUP_ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("prune_remote_backups", content)
        self.assertNotIn("rclone delete", content)
        self.assertNotIn("rclone cleanup", content)
        self.assertNotIn("--retention-days", content)
        self.assertNotIn("--prune-only", content)

    def test_entrypoint_excludes_retention_flags(self):
        """Ensure entrypoint.sh does not export client-side pruning environment variables."""
        content = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertNotIn("BACKUP_RETENTION_DAYS", content)
        self.assertNotIn("DRY_RUN", content)

    def test_backup_engine_preserves_upload_verification(self):
        """Ensure backup-engine.sh retains affirmative cloud upload verification."""
        content = BACKUP_ENGINE.read_text(encoding="utf-8")
        self.assertIn("Verifying cloud upload", content)
        self.assertIn("Upload verification failed", content)
        self.assertIn("Cloud upload verified successfully", content)

    def test_backup_architecture_documents_b2_lifecycle_rules(self):
        """Ensure docs/BACKUP_ARCHITECTURE.md documents B2 lifecycle rules and least privilege."""
        self.assertTrue(BACKUP_ARCH_DOC.exists(), "docs/BACKUP_ARCHITECTURE.md must exist")
        content = BACKUP_ARCH_DOC.read_text(encoding="utf-8")

        # Must mention B2 lifecycle rules
        self.assertIn("Lifecycle", content)
        self.assertIn("daysFromUploadingToHiding", content)
        self.assertIn("daysFromHidingToDeleting", content)

        # Must document least-privilege security rationale (no deleteFiles needed)
        self.assertIn("Least Privilege", content)
        self.assertIn("deleteFiles", content)

    def test_runner_readme_documents_server_side_lifecycle(self):
        """Ensure tools/backup-runner/README.md documents B2 server-side lifecycle management."""
        self.assertTrue(RUNNER_README.exists(), "tools/backup-runner/README.md must exist")
        content = RUNNER_README.read_text(encoding="utf-8")

        self.assertIn("Lifecycle", content)
        self.assertNotIn("prune_remote_backups", content)
        self.assertNotIn("BACKUP_RETENTION_DAYS", content)

    def test_declarative_b2_lifecycle_rules_json_file(self):
        """Validate tools/backup-dr/b2-lifecycle-rules.json exists and adheres to B2 schema."""
        b2_rules_file = REPO_ROOT / "tools" / "backup-dr" / "b2-lifecycle-rules.json"
        self.assertTrue(b2_rules_file.exists(), "b2-lifecycle-rules.json must exist")
        data = json.loads(b2_rules_file.read_text(encoding="utf-8"))
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["fileNamePrefix"], "backups/")
        self.assertEqual(data[0]["daysFromUploadingToHiding"], 30)
        self.assertEqual(data[0]["daysFromHidingToDeleting"], 1)
        self.assertEqual(data[0]["daysFromStartingToCancelingUnfinishedLargeFiles"], 1)

    def test_declarative_s3_lifecycle_configuration_json_file(self):
        """Validate tools/backup-dr/s3-lifecycle-configuration.json exists and adheres to S3 schema."""
        s3_rules_file = REPO_ROOT / "tools" / "backup-dr" / "s3-lifecycle-configuration.json"
        self.assertTrue(s3_rules_file.exists(), "s3-lifecycle-configuration.json must exist")
        data = json.loads(s3_rules_file.read_text(encoding="utf-8"))
        self.assertIn("Rules", data)
        rules = data["Rules"]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["Filter"]["Prefix"], "backups/")
        self.assertEqual(rules[0]["Expiration"]["Days"], 30)
        self.assertEqual(rules[0]["NoncurrentVersionExpiration"]["NoncurrentDays"], 1)

    def test_manage_b2_lifecycle_utility_exists_and_executable(self):
        """Ensure tools/backup-dr/manage-b2-lifecycle.py exists and is executable."""
        script_path = REPO_ROOT / "tools" / "backup-dr" / "manage-b2-lifecycle.py"
        self.assertTrue(script_path.exists(), "manage-b2-lifecycle.py must exist")
        self.assertTrue(os.access(script_path, os.X_OK), "manage-b2-lifecycle.py must be executable")

    def test_entrypoint_cron_schedule_isolation(self):
        """Ensure entrypoint.sh supports BACKUP_CRON_SCHEDULE and BACKUP_CRON override."""
        content = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("BACKUP_CRON_SCHEDULE", content)
        self.assertIn("BACKUP_CRON", content)

    def test_actual_compose_cron_schedule_disambiguation(self):
        """Ensure actual/compose.yml isolates actual-backup cron schedule from auto-categorizer."""
        actual_compose = REPO_ROOT / "actual" / "compose.yml"
        content = actual_compose.read_text(encoding="utf-8")
        self.assertIn("BACKUP_CRON_SCHEDULE", content)
        self.assertIn("AUTO_CATEGORIZER_CRON_SCHEDULE", content)


if __name__ == "__main__":
    unittest.main()
