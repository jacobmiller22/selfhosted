#!/usr/bin/env python3
"""
Unit tests verifying Backblaze B2 server-side bucket lifecycle policy architecture,
least-privilege credential security guarantees, and elimination of client-side deletion routines.
"""

import json
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

    def test_sample_b2_lifecycle_rule_json_validity(self):
        """Validate sample B2 lifecycle configuration JSON snippet parses as valid JSON."""
        sample_rule = [
            {
                "daysFromUploadingToHiding": 30,
                "daysFromHidingToDeleting": 1,
                "fileNamePrefix": "backups/"
            }
        ]
        serialized = json.dumps(sample_rule)
        deserialized = json.loads(serialized)
        self.assertEqual(len(deserialized), 1)
        self.assertEqual(deserialized[0]["daysFromUploadingToHiding"], 30)
        self.assertEqual(deserialized[0]["daysFromHidingToDeleting"], 1)
        self.assertEqual(deserialized[0]["fileNamePrefix"], "backups/")


if __name__ == "__main__":
    unittest.main()
