# Combined release scope and remaining gates

The three planned stages are now combined in the 1.0.0-rc.2 source tree: in-game control, investigation/report workflows, authenticated live multi-server dashboard and outbound agents. The exact implemented scope is documented in README.md and RELEASE_NOTES.md.

Production qualification still requires the full native Linux/Windows build, staging BDS/Endstone behavior and ABI verification, real browser-to-agent-to-plugin control tests, deployment TLS checks, external integration tests and measured overhead. See SMOKE_TEST.md.

Not claimed: an incremental budgeted world scanner, exact per-entity tick timings, automatic whole-Python/JavaScript interpreter attribution, or a replacement for every advanced Spark viewer feature. The callback SDKs are deliberate opt-in instrumentation. A scan remains a cached/cooldown-protected loaded-metadata scan, so its main-thread cost must be measured.

Future improvements should preserve explicit measurement windows, symbol uncertainty, access isolation and local policy. No destructive one-click lag fix is part of this product.
