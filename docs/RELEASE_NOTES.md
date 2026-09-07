# OniProfiler powered by spark 1.0.0-rc.1

Combined implementation of the three planned release stages. This is a release candidate, not a claim of production qualification.

## In-game control

Guided recordings, readable health checks, background monitoring controls, report history, loaded-area inspection, dimension filters and local before/after baselines. Spark's native sampling, allocation mode and compatible profile format remain the engine. The original advanced command surface is retained with permissions.

## Investigation and evidence

Sustained incident detection with cooldowns, optional local recordings, direct-measurement comparisons, private report notes and native-profile summaries. Entity counts are investigation leads, not measured per-entity tick costs. Native summaries use self-weight without recursive double counting and label inferred categories and limited symbol coverage explicitly.

## Private network control

A self-hosted responsive dashboard, real SQLite-backed authentication and role grants, outbound agents, bounded telemetry/history, short-lived remote requests, exact session/boot checks, immutable receipts, expiring redacted report shares and audit records. Includes opt-in Python/JavaScript callback instrumentation, Node file exporting and a BDS-only experimental HTTP adapter. No automatic whole-interpreter attribution is claimed.

## Build and distribution

One GitHub workflow builds Linux x86-64 `.so` and Windows x86-64 `.dll` files, tests the components, packages corresponding native source, records dependency resolution and writes checksums. Version tags create draft prereleases only after all build jobs pass. An optional Pages workflow publishes only the offline report viewer.

## Release gates

The source-authoring environment compiled portable components and ran API, SDK and UI checks. The complete native dependency build, real BDS integration, Windows loading, external hosting integrations and profiler overhead still require the supplied staging checklist. Actual GitHub build results take precedence over this release note. Do not run alongside standalone Spark or automatically delete entities to address reported concentrations.
