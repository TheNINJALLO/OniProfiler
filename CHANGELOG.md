# Changelog

## 1.0.0-rc.2

Rebuilt the Linux plugin on Ubuntu 22.04 and added a packaging gate that rejects native binaries requiring a GLIBC version newer than 2.35. Raw `endstone_oniprofiler.so` and `endstone_oniprofiler.dll` files are now required release assets instead of being available only inside platform ZIPs. Added an early native-load log message and clearer installation guidance that distinguishes the game plugin from the optional control-plane wheel.

## 1.0.0-rc.1

Combined the three proposed stages into a single candidate: native in-game controls, evidence/incident workflows, private multi-server control plane and outbound agents, opt-in runtime SDKs, deploy examples and native Linux/Windows CI. Added replay-safe instance/session-specific requests, immutable acknowledgements, native-profile summaries, expiring redacted sharing and per-server role grants.

This version remains subject to a successful complete native build and real BDS staging validation. See docs/RELEASE_NOTES.md and VALIDATION.md.

## 0.1.0-preview.1

Initial source preview with in-game menus, portable diagnostic logic, local report writing and an offline browser viewer.
