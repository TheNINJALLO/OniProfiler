# OniProfiler powered by spark: validation record

Date: 2026-09-07  
Version: 1.0.0-rc.1  
Delivery: combined release-candidate source, GitHub build workflows, built Python control-plane wheel, offline viewer and clearly labeled UI previews.

## What actually passed

| Component | Executed result | Scope |
| --- | --- | --- |
| Portable native domain/report writer | 85 C++ checks | Health interpretation, missing data, incidents, loaded-area ranking, permissions/ownership, local reports, retention and filesystem handling. |
| Portable native command bridge | 29 C++ checks | Fixed protocol parsing, numeric bounds, action gates, expiry/boot checks, atomic claims, immutable receipts, duplicate prevention and interrupted-claim recovery. |
| Python tests | 78 tests | Real SQLite-backed API and agent tests, CSRF, scoped access, session/token changes, report sharing, profile parsing, runtime SDKs, source/packaging checks, workflow contracts and launcher signal-policy tests. Includes a compiled C++/Python command-wire contract check. |
| JavaScript tests | 28 tests | 20 report-data tests and 8 runtime-SDK tests. |
| Offline browser viewer | 34 checks | Actual bundled HTML and production CSP hashes at 1440x1080 and 390x844; imports, filtering, comparisons, keyboard tabs, unknown metrics, hostile text and clearing data. |
| Live dashboard browser DOM | 58 checks | Actual static assets at 1440x1050 and 390x844; explicit synthetic mocked API responses, sign-in/out, server switching, charts, guided requests, filters, notes, shares, role-based controls, modal cleanup and hostile text. |
| Real HTTP service and outbound agent | 15 checks | Installed wheel, real uvicorn process, HTTP login/cookies, security headers, real agent requests, SQLite state, synthetic plugin mailbox/receipts, reports, sharing and logout. |
| CTest | 5 of 5 suites passed | Portable C++, Python, report JavaScript, command bridge and runtime JavaScript. The real HTTP and browser scripts were also executed separately. |
| C++ warnings/sanitizers | Passed | Both portable executables built with GCC 14.2.0, C++20, -Wall -Wextra -Wpedantic -Werror, AddressSanitizer and UndefinedBehaviorSanitizer. Re-running those tests is not counted as extra independent checks. |
| Wheel build and installation | Passed | Built a real platform-independent Python wheel using the installed setuptools backend, installed it into an isolated target directory and ran the HTTP smoke and all four command help entry points. |
| Workflow/metadata structure | Passed | YAML and matrix/gate/artifact contracts, metadata version consistency, fail-on-missing binary checks and explicit LLVM checksum/signing-key verification requirements. This is not a GitHub workflow execution. |

No external requests were observed in the tested browser DOM flows. The dashboard DOM tests deliberately mock its API; they do not claim browser-to-service networking. The offline viewer retains its actual CSP hash protection in the test bundle. The live dashboard's strict response headers and API permissions are tested independently against the real application.

Browser navigation to local HTTP was blocked by the environment with ERR_BLOCKED_BY_ADMINISTRATOR. That restriction was not bypassed. The separate real HTTP service/agent test uses HTTP clients and synthetic plugin files, not a browser or Bedrock process.

## Native build attempt: blocked, not passed

A real full CMake configuration attempt reached its pinned Spark dependency fetch and failed:

```text
fatal: unable to access 'https://github.com/EndstoneMC/spark.git/': Could not resolve host: github.com
Failed to clone repository: 'https://github.com/EndstoneMC/spark.git'
Configuration return code: 1
```

The environment has GCC 14.2.0, Clang 17 and no installed Conan. The required native CI toolchain is Clang/LLVM 20. The container could not retrieve the required native source/dependencies. **No completed native `.so` or `.dll` was built, installed or included in this delivery.**

The full GitHub workflow was not run, and no repository push or release publication was performed. The target repository could not be resolved by the available GitHub connection during the task. Source can be published with the bundled local GitHub CLI helper or committed normally. Native compilation could reveal integration issues not exercised by portable tests; the pipeline intentionally fails rather than packaging a missing binary.

## Still requires real deployment evidence

The C++ control center, Endstone/BDS ABI and native sampling/allocation hooks have not been exercised inside a running Bedrock server. Windows native loading, actual Bedrock forms and disconnect/reload behavior, Linux/Windows graceful loader shutdown, whole-server sampling overhead and world-scan tick cost remain staging gates.

Docker/Compose/TLS deployment, a live browser connected through the production proxy, real Pterodactyl resource readings, Discord notifications, and the experimental BDS HTTP Script adapter were not deployed or runtime-tested here. Launcher signal-policy unit tests do not prove a particular Windows game loader handles Ctrl+Break correctly.

The runtime SDKs measure explicitly wrapped callbacks only. They are not complete interpreter attribution. Entity concentrations are not measured per-entity lag cost. Native call-tree categories are indicated evidence with bounded summaries, not proven causal diagnoses. No performance-improvement percentage is asserted.

Run docs/SMOKE_TEST.md with each actual native artifact. Keep GitHub prereleases as drafts until those gates have recorded evidence.

## Evidence and reproduction

The source contains the tests, `docs/test-evidence.txt`, exact upstream pins and build scripts. Reproduction commands are in docs/BUILD.md, docs/DASHBOARD.md and integrations/README.md. Test fixtures and screenshot values are synthetic and are not readings from the user's server.
