# OniProfiler powered by spark 1.0.0

First stable release of the combined in-game profiler controls, investigation workflow and private multi-server dashboard. The GLIBC-compatible rc.2 Linux plugin was confirmed to load on a live Endstone/BDS server before promotion. This records plugin discovery and native loading, not completion of every optional integration or performance gate.

## Loader and distribution

The Linux native plugin is rebuilt on Ubuntu 22.04 to remove the accidental GLIBC 2.38 requirement from rc.1. Packaging now rejects Linux binaries requiring anything newer than GLIBC 2.35. The raw `endstone_oniprofiler.so` and `endstone_oniprofiler.dll` are direct release assets with checksums, and the plugin emits an early load message before its post-world enable phase.

## In-game control

Guided recordings, readable health checks, background monitoring controls, report history, loaded-area inspection, dimension filters and local before/after baselines. Spark's native sampling, allocation mode and compatible profile format remain the engine. The original advanced command surface is retained with permissions.

## Investigation and evidence

Sustained incident detection with cooldowns, optional local recordings, direct-measurement comparisons, private report notes and native-profile summaries. Entity counts are investigation leads, not measured per-entity tick costs. Native summaries use self-weight without recursive double counting and label inferred categories and limited symbol coverage explicitly.

## Private network control

A self-hosted responsive dashboard, real SQLite-backed authentication and role grants, outbound agents, bounded telemetry/history, short-lived remote requests, exact session/boot checks, immutable receipts, expiring redacted report shares and audit records. Includes opt-in Python/JavaScript callback instrumentation, Node file exporting and a BDS-only experimental HTTP adapter. No automatic whole-interpreter attribution is claimed.

## Build and distribution

One GitHub workflow builds Linux x86-64 `.so` and Windows x86-64 `.dll` files, tests the components, publishes both raw binaries, packages corresponding native source, records dependency resolution and writes checksums. Version tags create gated drafts only after all build jobs pass; stable tags create normal releases and suffixed tags create prereleases. An optional Pages workflow publishes only the offline report viewer.

## Release gates

GitHub Actions completed the pinned native dependency build, plugin compilation, automated native tests and packaging on Linux x86-64 and Windows x86-64. Live Linux discovery/loading is confirmed. Windows server loading, the full in-game workflow, external hosting integrations and profiler overhead still require the supplied staging checklist. Do not run alongside standalone Spark or automatically delete entities to address reported concentrations.
