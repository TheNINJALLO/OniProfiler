#!/usr/bin/env python3
"""Explicit project-file allowlist for source archives and new-repository publishing."""
from __future__ import annotations
from pathlib import Path

ROOT_FILES = {
    "CMakeLists.txt", "conanfile.py", "LICENSE", "NOTICE", "README.md", "INSTALL.md", "CHANGELOG.md",
    "SECURITY.md", "CONTRIBUTING.md", "AGENTS.md", "VALIDATION.md", "VERSION", ".dockerignore", ".gitignore", ".gitattributes", ".conanrc",
}
FOLDERS = {"src", "tests", "tools", "web", "docs", "upstream", ".github", "controlplane", "integrations", "deploy"}
SUFFIXES = {".cpp", ".h", ".hpp", ".py", ".js", ".cjs", ".mjs", ".sh", ".ps1", ".service", ".example", ".html", ".css", ".md", ".json", ".toml", ".yml", ".yaml", ".txt"}

def project_files(root: Path) -> list[Path]:
    files = []
    candidates = {root/name for name in ROOT_FILES}
    candidates.add(root/".conan2/profiles/default")
    for name in FOLDERS:
        folder = root/name
        if folder.is_dir() and not folder.is_symlink():
            candidates.update(folder.rglob("*"))
    for path in sorted(candidates):
        relative = path.relative_to(root)
        parts = relative.parts
        if path.is_symlink() or not path.is_file() or any((root.joinpath(*parts[:n])).is_symlink() for n in range(1, len(parts))):
            continue
        if path.name in {"agent.toml", "credentials.json", "secrets.json", "config.production.toml"}:
            continue
        if any(p.endswith(".egg-info") or p in {"__pycache__", "node_modules", ".git", ".venv", "build", "dist", "oni-data", "agent-state", "secrets"} for p in parts):
            continue
        permitted = str(relative) in ROOT_FILES or relative.as_posix() == ".conan2/profiles/default"
        permitted = permitted or (parts[0] in FOLDERS and (path.suffix.lower() in SUFFIXES or path.name in {"Dockerfile", "Caddyfile", "LICENSE", "NOTICE"}) and not any(p.startswith(".env") for p in parts))
        if permitted:
            files.append(path)
    return files
