#!/usr/bin/env python3
"""Fail closed on inconsistent release metadata or missing native release assets."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
ROOT=Path(__file__).resolve().parents[1]

def verify(root: Path=ROOT) -> str:
    version=(root/'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-(?:rc|preview)\.\d+)?',version):
        raise ValueError('Invalid VERSION')
    for filename in ('src/oni/domain.h','src/plugin.cpp','tools/package.py'):
        if '"'+version+'"' not in (root/filename).read_text():
            raise ValueError('Release version differs in '+filename)
    pyversion=version.replace('-rc.','rc').replace('-preview.','a')
    if tomllib.loads((root/'controlplane/pyproject.toml').read_text())['project']['version']!=pyversion:
        raise ValueError('Python distribution version differs')
    manifest=json.loads((root/'upstream/manifest.json').read_text())
    if not manifest:
        raise ValueError('Missing upstream provenance')
    return version

def checksums(folder: Path) -> Path:
    files=sorted(p for p in folder.iterdir() if p.is_file() and p.name!='SHA256SUMS.txt')
    if not files: raise ValueError('No release files to hash')
    output=folder/'SHA256SUMS.txt'
    output.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files))
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag');p.add_argument('--checksums',type=Path);p.add_argument('--release-assets',type=Path)
    a=p.parse_args();v=verify()
    if a.tag and a.tag!='v'+v: p.error('Tag must exactly match v'+v)
    if a.release_assets:
        for platform in ('linux-x86_64','windows-x86_64'):
            for suffix in ('','-source'):
                target=a.release_assets/f'OniProfiler-{v}-{platform}{suffix}.zip'
                if not target.is_file() or target.stat().st_size==0: p.error('Missing release asset '+target.name)
        if not list(a.release_assets.glob('oniprofiler_control-*.whl')): p.error('Control-plane wheel is missing')
    if a.checksums: print(checksums(a.checksums))
    print('Consistent release metadata: '+v)
if __name__=='__main__':main()
