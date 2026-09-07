# OniProfiler powered by spark

**Private performance investigations for Minecraft Bedrock servers.** A combined release-candidate implementation of the in-game control center, investigation tools and live multi-server dashboard.

Version: **1.0.0-rc.1**. Native engine: EndstoneMC/spark 0.5.3 at the exact commit recorded in `upstream/manifest.json`.

> This checkout is source. The supplied environment has not compiled a complete native `.so` or `.dll`, run the GitHub workflow, or loaded the plugin in BDS. The portable C++, control service and interface tests are documented in [VALIDATION.md](VALIDATION.md). Use the native CI and staging gates before production.

## Start here

**Need the plugin file?** Follow [docs/BUILD.md](docs/BUILD.md). Commit this project's contents to your own GitHub repository, then use **Actions > Build OniProfiler**. A successful run supplies `endstone_oniprofiler.so` and `endstone_oniprofiler.dll` plus source packages and checksums. No separate Spark installation is needed or appropriate alongside OniProfiler.

**Need the live dashboard?** Follow [docs/DASHBOARD.md](docs/DASHBOARD.md). The Python distribution contains the API, responsive browser interface, outbound agent, local administrator tools and startup wrapper. The native plugin remains usable without the dashboard.

**Need callback attribution?** See [integrations/README.md](integrations/README.md). It is opt-in instrumentation, not an invisible rewrite of every installed plugin.

## What is included

| Area | Implementation |
| --- | --- |
| In-game controls | `/oniprofiler` and `/oniprof`, guided investigation presets, recording ownership, stop/save/discard, readable health, reports and monitoring settings. |
| Busy areas | Loaded-chunk entity concentrations, dimension filtering, type breakdowns, timestamped snapshots and local baselines. Counts are not per-entity CPU measurements. |
| Incidents | Sustained thresholds, cooldowns, optional local profiling and reports. Background-resumption policy is explicit. |
| Evidence | Missing data remains unavailable, sample windows are shown, comparisons warn about workload differences, and native protobuf summaries retain measurement/interpretation boundaries. |
| Multi-server dashboard | Private login, fleet status, actual history, guided recordings, server-scoped roles, report notes/tags/comparisons, export and expiring redacted shares. |
| Outbound agent | Verified HTTPS, local mailbox, exact boot/session checks, command expiry, acknowledgements, reconnect/backoff, report synchronization and optional raw-profile upload. |
| Runtime integrations | Python sync/async timing, JavaScript timing core, Node atomic-file exporter, and a BDS-only experimental HTTP publisher using a write-only runtime key. |
| Hosting context | Optional explicitly selected cgroup v2 metrics, Pterodactyl resource readings, reduced Discord incident notices and a startup wrapper. |
| Build and operations | Linux/Windows native workflows, application wheel, portable and API/UI tests, Docker Compose and systemd examples, draft prerelease gate and source/checksum packages. |

## Architecture

```text
Bedrock + Endstone/Onistone
  OniProfiler C++ plugin (Spark native engine + forms + reports)
       private local files and a bounded command mailbox
  OniProfiler outbound Python agent
       verified HTTPS, scoped token, no game-host listener
  Private central API + SQLite + responsive dashboard
       viewer / operator / manager grants for each server
```

Native profiling runs in-process. The dashboard is not hosted by the game-thread code. Disk report handling and remote networking use the dedicated writer/agent. Loaded-world inspection still touches server APIs on the server thread and must be benchmarked under your workload; no zero-overhead claim is made.

## Defaults that matter

Remote control and remote management are **off** until enabled in the generated `oniprofiler.toml`. The dashboard has no default administrator password. A newly enrolled agent synchronizes private JSON reports; native file uploads are **off** until explicitly enabled. Shared reports redact location and identity information by default. There is no remote shell, arbitrary console endpoint, automatic entity purge or automatic plugin disabling.

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
