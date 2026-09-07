# Architecture

## Integration boundaries

The project contains original control/reporting code and an identifiable pinned
Spark dependency. CMake fetches the inspected Spark commit, applies narrow
content-verified patches, and links `spark_application` and
`spark_papi_integration` into **one** `endstone_oniprofiler` plugin. The upstream
standalone `spark` plugin target is excluded from default builds and is not
packaged. Endstone adapters supply world metadata and player/server bindings.

`tools/patch_engine.py` validates the original Git blob hashes before modifying
anything. It exposes structured native session status and export receipts,
adds the explicit background-resume policy, pins Endstone/PAPI headers, and fixes
upstream Python test paths for use as a CMake subproject. Repeated configuration
reverses its own exact patch for verification and reapplies it deterministically.
Unexpected source or ambiguous anchors fail the build.

The integration does not parse chat messages to infer recording success. Guided
presets use the native command handler's argument validation directly; session
status and completion are read as typed values. Native sample counts, dropped
samples and export outcomes are captured in a receipt before a background
session can replace that state.

## Code map

| Location | Responsibility |
| --- | --- |
| `src/plugin.cpp` | Endstone bootstrap, lifecycle, API adapters, permissions and command entry points. |
| `src/oni/control_center.*` | Forms, cached snapshots, recording workflows, receipts and incident orchestration. |
| `src/oni/domain.h` | Dependency-free interpretation rules, JSON escaping, rankings, presets, incident/ownership/legacy-command policy. |
| `src/oni/options.*` | Strict managed TOML configuration. |
| `src/oni/report_writer.*` | Bounded worker queue, atomic summary replacement, retention and periodic native-file size observations. |
| `src/oni/dashboard_connector.*` | Native verified-HTTPS heartbeat/report synchronization and fixed-command mailbox delivery. No Endstone objects cross into this worker. |
| `web/` | Static offline report UI with schema validation and local comparisons. |
| `tests/` | Portable domain/writer/tool/viewer checks and optional browser integration test. |
| `upstream/manifest.json` | Explicit provenance, pins and validation status. |

## Threading and costs

Endstone calls remain on the primary server thread. Statistics and native
session data are read there. Only immutable JSON strings and managed file paths
cross into the report writer's worker. Shutdown cancels UI callbacks via a weak
lifetime token, closes tracked forms, drains the report writer and uses Spark's
native shutdown sequence. Hot unloading is not a supported deployment workflow;
use a full server stop/restart.

The incident detector allocates no objects per tick. Health refreshes use cached
measurements at a configurable interval. Detailed area collection remains an
explicit, cooldown-protected **whole loaded-metadata scan**, not an incremental
budgeted scanner. Spark's existing metadata scans and symbol/export work remain
subject to upstream implementation costs. Benchmark the final native build on
representative staging workloads before making overhead claims.

## Data and evidence

Reports use `schema_version = 1` and the product string
`OniProfiler powered by spark`. Unknown numbers serialize as `null`. Health,
incident and recording summaries include the provenance pin, rolling windows,
findings, scope limitations, available history and native report references.
Recording summaries bind a receipt by native session start time and include
rolling before/after snapshots, not invented full-session averages.

No rule labels a native function, Python plugin, farm, chunk or entity as the
cause of lag. Aggregate findings explain the selected thresholds. The original
Spark profile remains the place to inspect call-tree evidence and symbol certainty.


## Combined live-control layer

`src/oni/command_bridge.*` and `bridge_protocol.h` implement a bounded local mailbox with strict field/action parsing, boot identity, session matching, expiry, atomic claims and immutable receipts. A worker handles files; at most one pending command is handed to the native control center per tick. Interrupted claimed files produce an indeterminate receipt on restart and are never replayed.

`controlplane/oniprofiler_control` contains the real API, SQLite store, authentication, optional external agent, local CLI and launcher. The native plugin has no public web listener. Its dashboard connector makes verified outbound HTTPS requests from a dedicated worker and exchanges only immutable local files with the main-thread control center. The optional external agent remains available for host/cgroup telemetry, runtime-source forwarding, local native-profile analysis and raw profile upload; it is not required for normal game-server linking. Callback SDKs write bounded immutable snapshots or use a scoped write-only ingestion endpoint. UI charts show actual transmitted history rather than synthetic production placeholders.

The control service protects each server with role grants and verifies a fresh snapshot before creating a command. The native bridge repeats its local policy/session checks. An applied stop receipt is separate from export completion. No arbitrary console command is accepted by the remote API.

The live browser interface uses normal API requests and isolated per-server state. Unit/integration tests exercise its SQLite-backed API independently; DOM tests inject explicit synthetic API fixtures into the actual static assets because browser network navigation was unavailable during authoring. They do not claim a live browser-to-native-server test.

## Native profile summaries

The agent's bounded protobuf reader understands the inspected Spark format, validates postorder trees and weight conservation, and summarizes self-weight without double-counting recursive inclusive weights. Keyword categories remain indicated evidence; unresolved and guessed frame labels are not converted to confirmed attribution. Summaries retain up to 16 threads and bounded top-frame lists. The full profile is still needed for detailed call-tree exploration.
