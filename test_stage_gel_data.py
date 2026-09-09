import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "stage", Path(__file__).parent / "scripts" / "stage_gel_data.py"
)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class StagingTests(unittest.TestCase):
    def test_sample_live_and_no_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True, text=True).stdout
            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            (root / "gel_data").mkdir()
            for name in ("snapshot.json", "snapshot_backup.json", "predictions.json"):
                (root / "gel_data" / name).write_text("{}")
            (root / "unrelated.txt").write_text("leave untracked")
            # Reproduce the old workflow: optional cache is absent in sample mode.
            old = subprocess.run(["git", "add", *stage.OUTPUTS], cwd=root,
                                 capture_output=True)
            self.assertNotEqual(old.returncode, 0)
            self.assertTrue(stage.stage_outputs(root))
            self.assertNotIn("unrelated.txt", git("diff", "--cached", "--name-only"))
            git("commit", "-m", "Sample snapshot")
            self.assertFalse(stage.stage_outputs(root))
            # A first live batch creates a previously untracked cache.
            (root / "gel_data" / "nbg_rates.csv").write_text("date,USD\n2026-09-09,2.7\n")
            self.assertTrue(stage.stage_outputs(root))
            self.assertIn("nbg_rates.csv", git("diff", "--cached", "--name-only"))
            git("commit", "-m", "Live cache")
            # History-only changes must also be persisted.
            (root / "gel_data" / "predictions.json").write_text("[{},{}]")
            self.assertTrue(stage.stage_outputs(root))
            self.assertEqual(git("diff", "--cached", "--name-only").strip(),
                             "gel_data/predictions.json")


if __name__ == "__main__":
    unittest.main()

