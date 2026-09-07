# Contributing

Keep new work separate from the identifiable Spark engine. Preserve credits and
GPL notices. Change dependency pins deliberately, re-inspect the affected native
APIs, update blob hashes, and rerun the native suite rather than weakening source
verification to make a build pass.

Use C++20 for native changes, Python 3.11+ for tools and dependency-free browser
JavaScript where practical. Run the documented portable checks and the required
native/staging checks for runtime changes. Add regression coverage for command
aliases, missing metrics, stale forms, permission changes, write failures and
shutdown behavior.

Never insert fabricated telemetry, guessed per-entity timing, external report
uploads without consent, credentials, server data or generated native artifacts
into source commits. Test fixtures and screenshots must say when values are
synthetic. Use accurate labels for implementation, compilation and runtime status.
