#!/usr/bin/env python3
"""Create a NEW OniProfiler GitHub repository using your authenticated GitHub CLI.

Private by default. --public explicitly opts into public source publication.
Never overwrites an existing repository or publishes server data/build folders.
A separate local checkout is retained for future work and recovery after errors.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from project_files import project_files

ROOT = Path(__file__).resolve().parents[1]

def owner_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value):
        raise argparse.ArgumentTypeError("Use a GitHub account login, not a URL or command.")
    return value

def run(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, env={**os.environ, "GH_HOST": "github.com"})
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(args[:3])}\n{result.stderr.strip()}")
    return result

def create_args(owner: str, checkout: Path, public: bool) -> list[str]:
    return ["gh", "repo", "create", owner + "/OniProfiler", "--public" if public else "--private",
            "--description", "OniProfiler powered by spark: guided native profiling and private performance reports for Endstone.",
            "--source", str(checkout), "--remote", "origin", "--push"]

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", type=owner_name, default="TheNINJALLO")
    parser.add_argument("--public", action="store_true", help="Explicitly publish the allowlisted project source publicly")
    parser.add_argument("--destination", type=Path, default=ROOT.parent/"OniProfiler-github")
    parser.add_argument("--dry-run", action="store_true", help="List files and intended repository without calling GitHub or writing files")
    args = parser.parse_args()
    files = project_files(ROOT)
    if not files or not (ROOT/"src"/"plugin.cpp").is_file():
        raise RuntimeError("The OniProfiler source tree is incomplete.")
    target = args.destination.resolve()
    if target == ROOT or ROOT in target.parents:
        raise RuntimeError("Choose a destination outside this source tree.")
    if args.dry_run:
        print(json.dumps({"repository": args.owner+"/OniProfiler", "visibility": "public" if args.public else "private",
            "destination": str(target), "files": [p.relative_to(ROOT).as_posix() for p in files]}, indent=2))
        return
    if target.exists():
        raise RuntimeError("Destination already exists. Nothing was changed. Choose a new --destination.")
    for executable in ["git", "gh"]:
        if not shutil.which(executable):
            raise RuntimeError(f"Install {executable} first. Authenticate locally with 'gh auth login --scopes workflow'; do not paste tokens into chat.")
    profile = json.loads(run(["gh", "api", "--hostname", "github.com", "user"]).stdout)
    if str(profile.get("login", "")).lower() != args.owner.lower():
        raise RuntimeError("The authenticated GitHub login does not match --owner. No repository was created.")
    existing = run(["gh", "api", "--hostname", "github.com", "repos/"+args.owner+"/OniProfiler", "--silent"], check=False)
    if existing.returncode == 0:
        raise RuntimeError("OniProfiler already exists. This helper never overwrites or pushes into an existing repository.")
    if "404" not in existing.stderr:
        raise RuntimeError("GitHub could not verify that the repository is absent. No repository was created.\n"+existing.stderr)
    target.mkdir(parents=True)
    for source in files:
        destination = target/source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    run(["git", "init", "-b", "main"], cwd=target)
    run(["git", "config", "user.name", profile["login"]], cwd=target)
    run(["git", "config", "user.email", str(profile["id"])+"+"+profile["login"]+"@users.noreply.github.com"], cwd=target)
    run(["git", "add", "--all"], cwd=target)
    run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "Initial OniProfiler powered by spark source preview"], cwd=target)
    try:
        result = run(create_args(args.owner,target,args.public),cwd=target)
    except RuntimeError:
        print("Local checkout retained at "+str(target)+". A failed create/push may have created an empty remote; inspect GitHub before retrying.",file=sys.stderr)
        raise
    print(result.stdout.strip())
    print("Published source checkout: "+str(target))
    print("Check GitHub Actions build results before installing a native artifact. No release tag was created.")

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
