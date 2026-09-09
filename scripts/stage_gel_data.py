"""Stage existing GEL outputs, including newly created cache/history files."""
from pathlib import Path
import subprocess


OUTPUTS = (
    "gel_data/snapshot.json",
    "gel_data/snapshot_backup.json",
    "gel_data/nbg_rates.csv",
    "gel_data/predictions.json",
)


def stage_outputs(root):
    existing = [path for path in OUTPUTS if (Path(root) / path).is_file()]
    if existing:
        subprocess.run(["git", "add", "--", *existing], cwd=root, check=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *OUTPUTS], cwd=root
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not inspect staged GEL outputs")
    return result.returncode == 1


if __name__ == "__main__":
    # Exit status indicates script success; the workflow separately checks changes.
    stage_outputs(Path.cwd())

