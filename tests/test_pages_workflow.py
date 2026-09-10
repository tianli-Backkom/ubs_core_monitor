import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


class PagesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_triggers_and_minimal_permissions(self):
        self.assertRegex(self.workflow, r"(?m)^\s{4}- cron: ['\"]30 23 \* \* \*['\"]$")
        self.assertRegex(self.workflow, r"(?m)^\s{2}workflow_dispatch:\s*$")
        self.assertRegex(self.workflow, r"(?ms)^\s{2}push:\s*\n\s{4}branches:\s*\[main\]")
        for permission in ("contents: read", "pages: write", "id-token: write"):
            self.assertEqual(self.workflow.count(permission), 1)

    def test_collection_validation_and_pages_upload_are_ordered(self):
        commands = [
            "python -X utf8 collect.py --all --days 30",
            "python -m unittest discover -s tests -v",
            "node --test tests/*.test.cjs",
            "python -X utf8 validate.py",
            "uses: actions/upload-pages-artifact@v3",
        ]
        positions = [self.workflow.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertRegex(self.workflow, r"(?ms)uses: actions/upload-pages-artifact@v3\s+with:\s+path: web\s*$")

    def test_cache_is_rolling_and_excludes_pages_artifact(self):
        for path in (
            "data/raw",
            "data/repos",
            "data/repositories.json",
            "data/efficiency.sqlite",
            "web/data",
        ):
            self.assertRegex(self.workflow, rf"(?m)^\s+{re.escape(path)}\s*$")
        self.assertIn("${{ github.run_id }}", self.workflow)
        self.assertIn("restore-keys:", self.workflow)
        self.assertNotIn("web/exports", self.workflow)

    def test_deploy_job_uses_pages_environment_and_concurrency(self):
        self.assertRegex(self.workflow, r"(?ms)^concurrency:\s*\n\s+group: pages\s*\n\s+cancel-in-progress: false")
        self.assertRegex(self.workflow, r"(?ms)^\s{2}deploy:\s*\n\s{4}needs: build\b")
        self.assertIn("name: github-pages", self.workflow)
        self.assertIn("uses: actions/deploy-pages@v4", self.workflow)


if __name__ == "__main__":
    unittest.main()
