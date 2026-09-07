#!/usr/bin/env python3
"""Package OniProfiler source or a CI build. Native packaging requires its source dependencies."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
from pathlib import Path
import zipfile
from project_files import project_files
from build_viewer import bundle

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0-rc.2"


MAX_LINUX_GLIBC = (2, 35)


def validate_binary(binary: Path, platform: str) -> None:
    if binary.is_symlink() or not binary.is_file() or binary.stat().st_size<1024:
        raise ValueError("Native binary is missing, a symlink or unexpectedly small")
    with binary.open("rb") as stream:
        head=stream.read(64)
        if platform=="linux-x86_64":
            if head[:6]!=b"\x7fELF\x02\x01" or struct.unpack_from("<H",head,18)[0]!=62 or struct.unpack_from("<H",head,16)[0]!=3:
                raise ValueError("Expected an x86-64 little-endian ELF shared library")
        else:
            if head[:2]!=b"MZ": raise ValueError("Expected a Windows PE library")
            offset=struct.unpack_from("<I",head,60)[0]
            if offset>binary.stat().st_size-24: raise ValueError("Invalid PE header offset")
            stream.seek(offset);pe=stream.read(24)
            if pe[:4]!=b"PE\0\0" or struct.unpack_from("<H",pe,4)[0]!=0x8664 or not struct.unpack_from("<H",pe,22)[0]&0x2000:
                raise ValueError("Expected an AMD64 PE DLL")

def validate_linux_glibc(binary: Path) -> None:
    versions={(int(major),int(minor)) for major,minor in re.findall(rb"GLIBC_(\d+)\.(\d+)",binary.read_bytes())}
    if not versions:
        raise ValueError("Linux plugin does not declare any GLIBC symbol versions")
    required=max(versions)
    if required>MAX_LINUX_GLIBC:
        raise ValueError(f"Linux plugin requires GLIBC_{required[0]}.{required[1]}; maximum supported baseline is GLIBC_{MAX_LINUX_GLIBC[0]}.{MAX_LINUX_GLIBC[1]}")

def source_archive(root: Path, output: Path, deps: Path | None = None) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        for file in project_files(root):
            archive.write(file, "OniProfiler/"+file.relative_to(root).as_posix())
        if deps:
            for name in ("conan.lock","conan-graph.json"):
                path=root/name
                if path.is_file(): archive.write(path,"OniProfiler/build-provenance/"+name)
            required = ("spark_engine-src", "endstone-src", "endstone_papi_headers-src", "funchook-src")
            for name in required:
                folder = deps/name
                if not folder.is_dir():
                    raise ValueError("Source dependency is missing: "+str(folder))
                for file in sorted(folder.rglob("*")):
                    rel = file.relative_to(folder)
                    if file.is_file() and not file.is_symlink() and not any(p in {".git","__pycache__","build","node_modules"} for p in rel.parts):
                        archive.write(file,"OniProfiler/upstream-src/"+name+"/"+rel.as_posix())
    return output

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,default=ROOT/"dist")
    p.add_argument("--build-dir",type=Path)
    p.add_argument("--platform",choices=["linux-x86_64","windows-x86_64"])
    args=p.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    if not args.build_dir:
        path=source_archive(ROOT,args.output/f"OniProfiler-{VERSION}-source.zip")
        print(path); return
    if not args.platform: p.error("--platform is required with --build-dir")
    suffix=".dll" if args.platform.startswith("windows") else ".so"
    binary=args.build_dir/("endstone_oniprofiler"+suffix)
    if not binary.is_file(): raise ValueError("Native binary was not built: "+str(binary))
    validate_binary(binary,args.platform)
    if args.platform=="linux-x86_64": validate_linux_glibc(binary)
    # Do not ship a native binary without the inspected/patched engine sources.
    from patch_engine import PATCHES, transform
    deps=args.build_dir/"_deps"
    for name,(sha,replacements) in PATCHES.items():
        data=(deps/"spark_engine-src"/name).read_bytes()
        if transform(data,sha,replacements)!=data: raise ValueError("Native source integration is not fully patched")
    licenses=args.build_dir/"third-party-licenses"
    if not (licenses/"manifest.json").is_file(): raise ValueError("Conan dependency license manifest is missing")
    source=source_archive(ROOT,args.output/f"OniProfiler-{VERSION}-{args.platform}-source.zip",deps)
    shutil.copy2(binary,args.output/binary.name)
    artifact=args.output/f"OniProfiler-{VERSION}-{args.platform}.zip"
    with zipfile.ZipFile(artifact,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.write(binary,binary.name)
        for file in sorted(licenses.rglob("*")):
            if file.is_file() and not file.is_symlink(): archive.write(file,"third-party-licenses/"+file.relative_to(licenses).as_posix())
        archive.writestr("OniProfiler-Report-Viewer.html",bundle(ROOT))
        pdb=binary.with_suffix(".pdb")
        if pdb.exists(): archive.write(pdb,pdb.name)
        for file in project_files(ROOT):
            rel=file.relative_to(ROOT)
            if rel.parts[0] in {"web","docs","integrations","deploy","controlplane"} or rel.as_posix() in {"LICENSE","NOTICE","README.md","INSTALL.md","VALIDATION.md"}:
                archive.write(file,rel.as_posix())
        for name in ("conan.lock","conan-graph.json"):
            path=ROOT/name
            if path.is_file(): archive.write(path,"build-provenance/"+name)
        archive.writestr("BUILD.json",json.dumps({"version":VERSION,"platform":args.platform,"runtime_tested":False,"git_commit":os.getenv("GITHUB_SHA","local"),"workflow_run":os.getenv("GITHUB_RUN_ID","not-run"),
            "source_archive":source.name,"binary_sha256":hashlib.sha256(binary.read_bytes()).hexdigest()},indent=2))
    print(source); print(artifact)

if __name__ == "__main__": main()
