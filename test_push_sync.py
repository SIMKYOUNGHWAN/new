from pathlib import Path
import subprocess
import tempfile
import unittest


class PushSyncTests(unittest.TestCase):
    def test_preserves_both_snapshots_after_remote_advance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(cwd, *args, check=True):
                return subprocess.run(["git", *args], cwd=cwd, check=check,
                                      capture_output=True, text=True)
            remote = root / "remote.git"
            git(root, "init", "--bare", str(remote))
            first, second = root / "gel", root / "krw"
            git(root, "clone", str(remote), str(first))
            git(first, "checkout", "-b", "main")
            git(first, "config", "user.name", "Test")
            git(first, "config", "user.email", "test@example.com")
            (first / "README.md").write_text("initial")
            git(first, "add", ".")
            git(first, "commit", "-m", "initial")
            git(first, "push", "-u", "origin", "main")
            git(root, "clone", "-b", "main", str(remote), str(second))
            git(second, "config", "user.name", "Test")
            git(second, "config", "user.email", "test@example.com")
            for repo, folder in ((first, "gel_data"), (second, "data")):
                (repo / folder).mkdir()
                (repo / folder / "snapshot.json").write_text("{}")
                git(repo, "add", folder)
                git(repo, "commit", "-m", folder)
            git(first, "push")
            self.assertNotEqual(git(second, "push", check=False).returncode, 0)
            git(second, "pull", "--rebase", "origin", "main")
            git(second, "push")
            self.assertTrue((second / "data/snapshot.json").exists())
            self.assertTrue((second / "gel_data/snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()

