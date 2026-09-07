# OniProfiler powered by spark

**Private performance investigations for Minecraft Bedrock servers.** A combined implementation of the in-game control center, investigation tools and live multi-server dashboard.

Version: **1.0.1**. Native engine: EndstoneMC/spark 0.5.3 at the exact commit recorded in `upstream/manifest.json`.

> Release binaries are compiled and tested by GitHub Actions, and the corrected Linux native plugin has been confirmed to load on a live Endstone/BDS server. The complete integration and overhead checklist in [VALIDATION.md](VALIDATION.md) remains the boundary for production claims.

## Start here

**Need the plugin file?** Download the raw `endstone_oniprofiler.so` (Linux) or `endstone_oniprofiler.dll` (Windows) from the GitHub release. Put that one file directly in the server's `plugins/` directory and fully restart the server. Do not put the release ZIP or `oniprofiler_control-*.whl` in `plugins/`; the wheel is the optional dashboard service. See [INSTALL.md](INSTALL.md).

**Need the live dashboard?** Follow [docs/DASHBOARD.md](docs/DASHBOARD.md). Install the Python distribution only on the central dashboard host. Each game server links directly from the native plugin over verified HTTPS; it does not need Python, a wheel, a startup wrapper or a second agent process.

**Need callback attribution?** See [integrations/README.md](integrations/README.md). It is opt-in instrumentation, not an invisible rewrite of every installed plugin.

## What is included

| Area | Implementation |
| --- | --- |
| In-game controls | `/oniprofiler` and `/oniprof`, guided investigation presets, recording ownership, stop/save/discard, readable health, reports and monitoring settings. |
| Busy areas | Loaded-chunk entity concentrations, dimension filtering, type breakdowns, timestamped snapshots and local baselines. Counts are not per-entity CPU measurements. |
| Incidents | Sustained thresholds, cooldowns, optional local profiling and reports. Background-resumption policy is explicit. |
| Evidence | Missing data remains unavailable, sample windows are shown, comparisons warn about workload differences, and native protobuf summaries retain measurement/interpretation boundaries. |
| Multi-server dashboard | Private login, fleet status, actual history, guided recordings, server-scoped roles, report notes/tags/comparisons, export and expiring redacted shares. |
| Native dashboard link | Verified outbound HTTPS from the plugin, local mailbox isolation, exact boot/session checks, command expiry, acknowledgements, reconnect/backoff and JSON report synchronization. No Python install is needed on a game server. |
| Runtime integrations | Python sync/async timing, JavaScript timing core, Node atomic-file exporter, and a BDS-only experimental HTTP publisher using a write-only runtime key. |
| Hosting context | Optional explicitly selected cgroup v2 metrics, Pterodactyl resource readings, reduced Discord incident notices and a startup wrapper. |
| Build and operations | GLIBC-compatible Linux and Windows native workflows, raw game-plugin downloads, application wheel, portable and API/UI tests, Docker Compose and systemd examples, gated releases and source/checksum packages. |

## Architecture

```text
Bedrock + Endstone/Onistone
  OniProfiler C++ plugin (Spark native engine + forms + reports)
       private files + bounded mailbox + native outbound HTTPS worker
  Private central API + SQLite + responsive dashboard
       viewer / operator / manager grants for each server
```

Native profiling runs in-process. The dashboard is not hosted by the game-thread code. Disk report handling and remote networking use dedicated workers that receive no Endstone objects. Loaded-world inspection still touches server APIs on the server thread and must be benchmarked under your workload; no zero-overhead claim is made.

## Defaults that matter

The dashboard link, remote control and remote management are **off** until enabled in the generated `oniprofiler.toml`. The dashboard has no default administrator password. The native link can synchronize private JSON reports; raw `.sparkprofile` upload remains an optional external-agent feature. Shared reports redact location and identity information by default. There is no remote shell, arbitrary console endpoint, automatic entity purge or automatic plugin disabling.

The supplied offline HTML viewer is separate from the authenticated dashboard. It opens locally imported reports and a clearly labeled synthetic demo. The optional Pages workflow publishes only that offline viewer, never credentials or report folders.

## Build and test

```bash
python -m pip install -e 'controlplane[test]'
cmake -S . -B build/offline -DONIPROFILER_OFFLINE_TESTS_ONLY=ON -DCMAKE_BUILD_TYPE=Debug
cmake --build build/offline --parallel 2
ctest --test-dir build/offline --output-on-failure
```

This runs portable components without fetching the native engine. [The full native instructions](docs/BUILD.md) use the pinned compiler family and verified upstream integration. A green portable build is not a native plugin artifact.

## Boundaries

Exact per-entity and per-block timings, automatic full Python/JavaScript interpreter attribution, a replacement for every advanced Spark viewer feature, and transparent resource-pack/client instrumentation are **not** claimed. The native summary categorizes identifiable sampled self-weight and labels uncertain symbols. Runtime SDKs time only wrapped callbacks and include waiting time for async work.

The BDS experimental HTTP adapter is source intended for the exact installed server module versions, not a prebuilt universally compatible `.mcaddon`. Deployment recipes and native runtime behavior require [staging verification](docs/SMOKE_TEST.md).

## Credits and license

OniProfiler is a modified integration powered by the EndstoneMC/spark native profiler and Spark's report ecosystem. It retains upstream identification, required notices and GPL-3.0 licensing. See [NOTICE](NOTICE), [LICENSE](LICENSE) and the pinned [upstream manifest](upstream/manifest.json). This project does not claim ownership of the original Spark engine and does not redistribute the Bedrock server executable.

The combined scope and remaining gates are recorded in [release notes](docs/RELEASE_NOTES.md). Security boundaries are in [SECURITY.md](SECURITY.md).
