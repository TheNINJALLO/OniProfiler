# OniProfiler powered by spark: validation record

Date: 2026-09-07  
Version: 1.0.0
Delivery: stable source, GitHub build workflows, built Python control-plane wheel, CI-built Linux/Windows native artifacts, raw plugin downloads, offline viewer and clearly labeled UI previews.

## What actually passed

| Component | Executed result | Scope |
| --- | --- | --- |
| Portable native domain/report writer | 85 C++ checks | Health interpretation, missing data, incidents, loaded-area ranking, permissions/ownership, local reports, retention and filesystem handling. |
| Portable native command bridge | 29 C++ checks | Fixed protocol parsing, numeric bounds, action gates, expiry/boot checks, atomic claims, immutable receipts, duplicate prevention and interrupted-claim recovery. |
| Python tests | 81 passed, 3 skipped, 32 subtests passed | Real SQLite-backed API and agent tests, CSRF, scoped access, session/token changes, report sharing, profile parsing, runtime SDKs, source/packaging checks, workflow contracts, GLIBC ceiling and launcher signal-policy tests. Includes a compiled C++/Python command-wire contract check. |
| JavaScript tests | 28 tests | 20 report-data tests and 8 runtime-SDK tests. |
| Offline browser viewer | 34 checks | Actual bundled HTML and production CSP hashes at 1440x1080 and 390x844; imports, filtering, comparisons, keyboard tabs, unknown metrics, hostile text and clearing data. |
| Live dashboard browser DOM | 58 checks | Actual static assets at 1440x1050 and 390x844; explicit synthetic mocked API responses, sign-in/out, server switching, charts, guided requests, filters, notes, shares, role-based controls, modal cleanup and hostile text. |
| Real HTTP service and outbound agent | 15 checks | Installed wheel, real uvicorn process, HTTP login/cookies, security headers, real agent requests, SQLite state, synthetic plugin mailbox/receipts, reports, sharing and logout. |
| CTest | 5 of 5 suites passed | Portable C++, Python, report JavaScript, command bridge and runtime JavaScript. The real HTTP and browser scripts were also executed separately. |
| C++ warnings/sanitizers | Passed | Both portable executables built with GCC 14.2.0, C++20, -Wall -Wextra -Wpedantic -Werror, AddressSanitizer and UndefinedBehaviorSanitizer. Re-running those tests is not counted as extra independent checks. |
| Wheel build and installation | Passed | Built a real platform-independent Python wheel using the installed setuptools backend, installed it into an isolated target directory and ran the HTTP smoke and all four command help entry points. |
| GitHub workflow and metadata | Passed | Release-candidate run [34152091512](https://github.com/TheNINJALLO/OniProfiler/actions/runs/34152091512) completed at commit `224bc74`: application checks, Ubuntu 22.04 and Windows native matrices, native tests, GLIBC/package checks, raw artifact uploads and draft assembly all passed. |

No external requests were observed in the tested browser DOM flows. The dashboard DOM tests deliberately mock its API; they do not claim browser-to-service networking. The offline viewer retains its actual CSP hash protection in the test bundle. The live dashboard's strict response headers and API permissions are tested independently against the real application.

Browser navigation to local HTTP was blocked by the environment with ERR_BLOCKED_BY_ADMINISTRATOR. That restriction was not bypassed. The separate real HTTP service/agent test uses HTTP clients and synthetic plugin files, not a browser or Bedrock process.

## Native build, CI and observed loading

GitHub Actions run [34152091512](https://github.com/TheNINJALLO/OniProfiler/actions/runs/34152091512) completed successfully for commit `224bc740c7d9d05c969eb92a5b3bbf1c9dd4e81c`. Both native matrices used runner-image-isolated Conan caches and LLVM 20 toolchains, configured the pinned Spark and Endstone integration, built the plugin and tests, passed CTest, and passed the packaging/checksum gates. The Linux binary was built on Ubuntu 22.04 and independently inspected with a maximum required symbol version of GLIBC 2.35.

The run uploaded raw `endstone_oniprofiler.dll` and `endstone_oniprofiler.so` plugin artifacts, Windows and Linux release packages with corresponding source/notices, native diagnostics, the Python application package, dashboard/agent assets and interface-test evidence. The resulting rc.2 release checksums were independently verified before publication.

The server owner reported that the corrected rc.2 raw Linux plugin loads and works in a live Endstone/BDS container. The earlier rc.1 artifact had failed at load time because it required GLIBC 2.38. This field report confirms Linux discovery and native loading for that environment; it does not by itself verify every command, profiler mode, shutdown path, Windows deployment or performance characteristic.

## Still requires real deployment evidence

Windows native loading, complete Bedrock form and permission coverage, disconnect/reload behavior, Linux/Windows graceful loader shutdown, all sampling/allocation modes, whole-server sampling overhead and world-scan tick cost remain staging gates.

Docker/Compose/TLS deployment, a live browser connected through the production proxy, real Pterodactyl resource readings, Discord notifications, and the experimental BDS HTTP Script adapter were not deployed or runtime-tested here. Launcher signal-policy unit tests do not prove a particular Windows game loader handles Ctrl+Break correctly.

The runtime SDKs measure explicitly wrapped callbacks only. They are not complete interpreter attribution. Entity concentrations are not measured per-entity lag cost. Native call-tree categories are indicated evidence with bounded summaries, not proven causal diagnoses. No performance-improvement percentage is asserted.

Run docs/SMOKE_TEST.md with each actual native artifact. Stable versioning records the confirmed Linux load and automated gates; it is not a claim that every optional deployment and performance gate is complete.

## Evidence and reproduction

The source contains the tests, `docs/test-evidence.txt`, exact upstream pins and build scripts. Reproduction commands are in docs/BUILD.md, docs/DASHBOARD.md and integrations/README.md. Test fixtures and screenshot values are synthetic and are not readings from the user's server.
