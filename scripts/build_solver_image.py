"""Build only the small reviewed solver context, never the workspace or user data."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dayan.solvers.sandbox import DEFAULT_IMAGE, bundle_fingerprint, image_contract

if __name__ == "__main__":
    fingerprint = bundle_fingerprint()
    subprocess.run(["docker", "build", "--platform=linux/amd64", "--build-arg", "DAYAN_SOLVER_BUNDLE=" + fingerprint,
                    "--tag", DEFAULT_IMAGE, str(ROOT / "dayan/solvers")], check=True)
    print(image_contract())
