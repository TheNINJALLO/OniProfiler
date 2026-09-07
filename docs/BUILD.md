# Build the installable plugins

## The shortest GitHub route

1. Extract the project. Put the **contents** of `OniProfiler/`, including `.github`, at the root of your new repository. Do not upload the enclosing ZIP as the only repository file.
2. Commit to `main`. The **Build OniProfiler** workflow runs automatically. It also supports **Actions > Build OniProfiler > Run workflow** and pull requests.
3. Open that run. Wait for the application checks and both native platform jobs to finish successfully. A green portable test alone does not mean the plugin compiled.
4. Under **Artifacts**, download `endstone_oniprofiler.so` for Linux or `endstone_oniprofiler.dll` for Windows. Published releases expose those raw binaries as direct assets. The `OniProfiler-linux-x86_64` and `OniProfiler-windows-x86_64` artifacts also include release ZIPs and matching source archives.
5. Use a staging server first. Stop it, remove the standalone Spark binary, put **one** OniProfiler binary in `plugins/`, and restart. Run `/oniprofiler`. Do not load two native samplers together.

Native compilation and automated tests do not replace BDS loader/runtime verification. Use a staging server and record the checks in `docs/SMOKE_TEST.md`.

## Publish from a local terminal

Git, Python and GitHub CLI must be installed. Authentication stays on your computer:

```bash
gh auth login --hostname github.com --scopes workflow
python tools/publish.py --owner TheNINJALLO --public
```

The helper only creates a **new** repository and refuses to overwrite an existing one. It excludes runtime reports, credentials, databases and build caches. It leaves a normal editable checkout at `../OniProfiler-github`.

## What the workflow does

`build.yml` first tests the portable C++, real SQLite-backed API, agent, Python and JavaScript integrations, offline viewer and dashboard DOM. It packages the control-plane wheel and source.

The two native jobs install Clang/libc++ 20 on Ubuntu 22.04 or LLVM/clang-cl 20.1.8 plus the x64 Windows SDK on Windows 2025. Ubuntu 22.04 provides the supported older GLIBC baseline, and packaging rejects a binary requiring anything newer than GLIBC 2.35. The Windows installer has a pinned official SHA-256. The Linux apt signing key fingerprint is verified. Conan 2.29.1 resolves the declared versions, records recipe revisions in a per-run lock, and builds missing dependencies.

CMake fetches the pinned Spark commit and verifies every integration patch against known content hashes. Endstone and PAPI references are pinned. A changed or incomplete upstream integration fails configuration rather than producing an improvised plugin.

Native CTest runs before packaging. Packaging refuses missing, wrong-format or wrong-architecture plugin files and requires the patched native source dependencies. Platform packages include checksums, dependency resolution metadata and the matching source ZIP. Windows PDB files are retained when generated. Build diagnostics are uploaded even when a job fails.

A pushed tag exactly matching `VERSION`, currently `v1.0.0`, assembles a **draft release only after all jobs pass**. Tags containing a prerelease suffix are marked as prereleases; stable tags are not. Review the staging checklist before publishing. Build success alone is not a claim of complete BDS compatibility or performance overhead.

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Local native build

Use the same compiler and SDK as CI. On Linux, run `bash tools/ci/install-llvm-linux.sh` on a disposable Ubuntu 22.04 build machine. It installs an apt repository and requires sudo. On Windows, use an x64 VS developer terminal and LLVM 20.1.8; the installer script is designed for GitHub's `RUNNER_TEMP` and `GITHUB_PATH` environment.

```bash
python -m pip install 'conan==2.29.1' 'cmake==3.31.6' 'ninja==1.11.1.3' -e 'controlplane[test]'
conan lock create . --lockfile-out=conan.lock
conan install . --lockfile=conan.lock --build=missing
cmake --preset conan-relwithdebinfo
cmake --build --preset conan-relwithdebinfo --parallel 2
ctest --test-dir build/RelWithDebInfo --output-on-failure
```

Native output: `build/RelWithDebInfo/endstone_oniprofiler.so` or `.dll`.
A CI corresponding-source archive includes `upstream-src/`; CMake selects those bundled engine checkouts automatically. Conan dependencies still need a configured package cache or network access. Recipe revisions are recorded per build, not claimed globally byte-for-byte reproducible. The build does not redistribute the proprietary Bedrock server executable.

## Tests without native dependencies

```bash
python -m pip install -e 'controlplane[test]'
cmake -S . -B build/offline -DONIPROFILER_OFFLINE_TESTS_ONLY=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build build/offline --parallel 2
ctest --test-dir build/offline --output-on-failure
```

This mode does not build a plugin and does not exercise the BDS ABI.
