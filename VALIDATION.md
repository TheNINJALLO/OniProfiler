# OniProfiler powered by spark: validation record

Date: 2026-09-07  
Version: 1.0.1
Delivery: v1.0.1 source and local release checks complete; tagged Linux/Windows artifacts remain gated on the GitHub workflow recorded below after it runs.

## What actually passed

| Component | Executed result | Scope |
| --- | --- | --- |
| Portable native domain/report writer | 82 C++ checks | Health interpretation, missing data, incidents, loaded-area ranking, permissions/ownership, local reports, retention and filesystem handling. |
| Portable native command bridge | 31 C++ checks | Fixed protocol parsing, native command batching, numeric bounds, action gates, expiry/boot checks, atomic claims, immutable receipts, duplicate prevention and interrupted-claim recovery. |
| Native managed options | 11 C++ checks | Dashboard config generation/migration, quoting, HTTPS origin normalization, token validation and Linux owner-only permission policy. |
| Python tests | 82 passed, 3 skipped | Real SQLite-backed API and optional-agent tests, native plugin endpoints, canonical origins, CSRF, scoped access, session/token changes, report sharing, profile parsing, runtime SDKs, source/packaging checks, GLIBC ceiling and launcher signal-policy tests. Includes a compiled C++/Python command-wire contract check when built through CTest. |
| JavaScript tests | 28 tests | 20 report-data tests and 8 runtime-SDK tests. |
| Offline browser viewer | Pending v1.0.1 workflow rerun | The retained 34-check suite covers actual bundled HTML and production CSP hashes at desktop and mobile sizes. |
| Live dashboard browser DOM | Pending v1.0.1 workflow rerun | The 58-check suite covers actual static assets with explicit synthetic mocked API responses, including the changed server-link wording. |
| Real HTTP service and outbound agent | 15 checks | Installed wheel, real uvicorn process, HTTP login/cookies, security headers, real agent requests, SQLite state, synthetic plugin mailbox/receipts, reports, sharing and logout. |
| CTest | 5 of 5 portable suites passed | Portable C++, Python, report JavaScript, command bridge and runtime JavaScript. The real HTTP script was also executed separately. |
| C++ warnings | Passed locally for changed native sources | The connector and options sources compiled as C++20 with MSVC 19.44, `/W4` and strict conformance. Full pinned LLVM builds remain a workflow gate. |
| Wheel build and installation | Passed | Built a real platform-independent Python wheel using the installed setuptools backend, installed it into an isolated target directory and ran the HTTP smoke and all four command help entry points. |
| GitHub workflow and metadata | Pending for v1.0.1 | v1.0.0 workflow evidence remains historical; v1.0.1 will not be released until its Ubuntu 22.04 and Windows native matrices pass. |

No external requests were observed in the tested browser DOM flows. The dashboard DOM tests deliberately mock its API; they do not claim browser-to-service networking. The offline viewer retains its actual CSP hash protection in the test bundle. The live dashboard's strict response headers and API permissions are tested independently against the real application.

Browser navigation to local HTTP was blocked by the environment with ERR_BLOCKED_BY_ADMINISTRATOR. That restriction was not bypassed. The separate real HTTP service/agent test uses HTTP clients and synthetic plugin files, not a browser or Bedrock process.

## Native build, CI and observed loading

The complete v1.0.1 pinned native build is pending its release workflow. Local CMake verified the exact Spark source integration, but this workstation does not have the project-required Windows clang-cl 20 compiler; no local full-plugin binary is claimed.

Historical v1.0.0 GitHub Actions run [34152091512](https://github.com/TheNINJALLO/OniProfiler/actions/runs/34152091512) completed successfully for commit `224bc740c7d9d05c969eb92a5b3bbf1c9dd4e81c`. Both native matrices used runner-image-isolated Conan caches and LLVM 20 toolchains, configured the pinned Spark and Endstone integration, built the plugin and tests, passed CTest, and passed the packaging/checksum gates. The Linux binary was built on Ubuntu 22.04 and independently inspected with a maximum required symbol version of GLIBC 2.35.

The server owner reported that the corrected v1.0.0/rc.2 raw Linux plugin loads and works in a live Endstone/BDS container. The earlier rc.1 artifact had failed at load time because it required GLIBC 2.38. This is historical loader evidence; it does not establish v1.0.1 native dashboard behavior.

## Still requires real deployment evidence

Windows native loading, complete Bedrock form and permission coverage, disconnect/reload behavior, Linux/Windows graceful loader shutdown, all sampling/allocation modes, whole-server sampling overhead and world-scan tick cost remain staging gates.

Docker/Compose/TLS deployment, a live browser connected through the production proxy, real Pterodactyl resource readings, Discord notifications, and the experimental BDS HTTP Script adapter were not deployed or runtime-tested here. Launcher signal-policy unit tests do not prove a particular Windows game loader handles Ctrl+Break correctly.

The runtime SDKs measure explicitly wrapped callbacks only. They are not complete interpreter attribution. Entity concentrations are not measured per-entity lag cost. Native call-tree categories are indicated evidence with bounded summaries, not proven causal diagnoses. No performance-improvement percentage is asserted.

Run docs/SMOKE_TEST.md with each actual native artifact. Stable versioning records the confirmed Linux load and automated gates; it is not a claim that every optional deployment and performance gate is complete.

## Evidence and reproduction

The source contains the tests, `docs/test-evidence.txt`, exact upstream pins and build scripts. Reproduction commands are in docs/BUILD.md, docs/DASHBOARD.md and integrations/README.md. Test fixtures and screenshot values are synthetic and are not readings from the user's server.
