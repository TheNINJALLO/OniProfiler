# OniProfiler powered by spark 1.0.3

Rebuilds against Endstone 0.11.15 SDK `b4aaa87d2c5305e7d340168f824ac2e2ea722e44` for BDS 1.26.60.6. The pinned Spark engine and source-verification guards are preserved.

The Linux x86-64 artifact passed native CTest (33 suites), offline CTest (3 suites, including 82 Python tests), 28 JavaScript tests, the GLIBC <=2.35 package gate, disposable-server recording/export/shutdown, and a protocol-2225 client form open/cancel check. Exact artifact identity and scope are in `docs/validation-endstone-0.11.15.json`.

Both native CI builds and application/browser gates passed in run [41569224346](https://github.com/TheNINJALLO/OniProfiler/actions/runs/41569224346). The exact Windows DLL also passed six disposable-server checks covering load, recording/export and clean shutdown; see `docs/validation-windows-endstone-0.11.15.json`. Linux release bytes retain the original local runtime qualification; Windows bytes and corresponding source come from CI. Release-documentation updates preserve runtime source bytes.

Retail clients, complete form coverage, optional integrations and performance staging remain pending. Download the raw `.so` or `.dll` for the game server; the optional control-plane wheel belongs on the dashboard host. Source and notices retain GPL-3.0 attribution to EndstoneMC/spark. Earlier release notes follow.

# OniProfiler powered by spark 1.0.1

OniProfiler 1.0.1 removes the Python-agent requirement from normal Endstone/Onistone server deployments. The native plugin now links directly to the private dashboard over verified outbound HTTPS while keeping all Endstone APIs on the server thread.

## Native dashboard link

- Adds an HTTPS-only native connector using the existing pinned libcurl dependency.
- Sends fresh plugin snapshots and private JSON reports without a wheel, Python runtime, startup wrapper or separate agent process on the game server.
- Receives only the existing fixed, allowlisted profiler protocol through the durable local mailbox. Commands remain instance-bound, expiring, session-aware and subject to local control/management gates.
- Sends immutable command receipts and keeps bounded retry state across restarts.
- Performs networking and file synchronization on a dedicated worker that never receives Endstone players, worlds, chunks, command senders or server objects.

## Enrollment and configuration

The generated `plugins/oniprofiler/oniprofiler.toml` now includes `dashboard_enabled`, `dashboard_url`, `dashboard_token`, `dashboard_poll_seconds` and `dashboard_sync_reports`. Older managed configs gain these disabled defaults automatically while retaining recognized settings. HTTPS origins and token formats are validated at startup, symlink configs are refused, and Linux config/mailbox files are restricted to the server account.

The dashboard's one-time server-token dialog now gives the exact native plugin settings. Connection labels use “server link” instead of implying that an external agent must be installed. The optional Python agent remains available only for advanced host/cgroup/Pterodactyl context, runtime forwarding, local native-profile analysis and explicitly enabled raw-profile upload.

## Dashboard reliability

Browser-origin comparison now canonicalizes scheme/hostname casing, a trailing slash and default HTTP/HTTPS ports. This fixes valid deployments being rejected with `Request origin does not match this dashboard` while retaining same-origin CSRF enforcement.

## Distribution and boundaries

The central dashboard still uses `oniprofiler_control-1.0.1-py3-none-any.whl`; install that wheel only on the dashboard host. Endstone servers require only `endstone_oniprofiler.so` or `endstone_oniprofiler.dll`. Raw `.sparkprofile` files remain local under the native link and still require the optional external agent for deliberate upload.

Release artifacts are built from the pinned Spark integration on Ubuntu 22.04 and Windows with LLVM 20. Packaging continues to reject a Linux plugin requiring newer than GLIBC 2.35. Live Linux loading was confirmed for v1.0.0; the supplied staging checklist remains required for v1.0.1 deployment and performance validation.
