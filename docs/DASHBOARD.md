# Private live dashboard and native server links

The native plugin works without a dashboard. For the combined system, run one central dashboard and enable the native link in each Minecraft server's plugin config. The plugin reads its timestamped telemetry and reports, synchronizes them over verified outbound HTTPS, and delivers a fixed set of profiler requests through its private local mailbox. It never exposes a network listener on a Minecraft server, and the game-server container does not need Python or a wheel.

## Central dashboard with Docker Compose

Point a DNS hostname at this machine and allow TCP 80/443 for the TLS proxy. The example hostname is not a deployed service. From the project root:

```bash
export ONI_HOSTNAME=profiler.example.com
docker compose -f deploy/compose.yml build
docker compose -f deploy/compose.yml run --rm dashboard oniprofiler-admin init
docker compose -f deploy/compose.yml up -d
```

`init` prompts privately for the first administrator username and a password of at least 14 characters. No default password is shipped. Keep `ONI_HOSTNAME` set for subsequent Compose commands or set it in a private local environment file that is not committed. The `oni-data` volume contains private SQLite data and synchronized profiles. Back it up and protect it.

The Compose deployment exposes only the TLS proxy, not the API's internal port. The Docker base images use maintained minor/major channels, not immutable digests. Validate and pin image digests under your deployment update policy. Docker deployment itself was not exercised in the build environment.

## Central dashboard without Docker

Install the included `oniprofiler_control-1.0.1-py3-none-any.whl` into Python 3.11+ in a virtual environment. This is the external dashboard package, not the game plugin, and must not be placed in the Endstone `plugins/` directory. It also retains an optional advanced-agent command for specialized deployments. Alternatively install `./controlplane` from source:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install ./controlplane
export ONI_DATA_DIR=/var/lib/oniprofiler
export ONI_PUBLIC_ORIGIN=https://profiler.example.com
oniprofiler-admin init
oniprofiler-server --host 127.0.0.1 --port 8080
```

Create the data directory with ownership matching the service user first. Put a TLS reverse proxy in front of loopback port 8080. Preserve the original `Host`; it must match `ONI_PUBLIC_ORIGIN`. Use one application worker with this SQLite deployment. Systemd examples are in `deploy/`; edit users and paths before installing them. The application disables access logs. Avoid proxy logs that record full share URLs.

## Enroll each Minecraft server

Sign in, open **Access & settings**, create the server and copy its one-time server-link token. Never paste an administrator session or an application-wide credential into a game add-on.

Start the native plugin once so it creates `plugins/oniprofiler/oniprofiler.toml`. Stop the server, then configure:

```toml
dashboard_enabled = true
dashboard_url = "https://oniprofiler.oninetwork.com"
dashboard_token = "paste-the-one-time-server-token-here"
dashboard_poll_seconds = 5
dashboard_sync_reports = true
```

Use the public HTTPS origin only, without a trailing path, query, `www` alias or internal port. Paste the raw server token without a `Bearer` prefix. Fully restart the server. A successful link prints `Native dashboard link connected` in the server log and the server becomes current in the dashboard. The plugin protects the managed config as owner-only on Linux because the token is a password.

Do **not** install `oniprofiler_control-*.whl` in the Endstone/Onistone server container. That wheel belongs on the central dashboard host only. Server-token rotation invalidates the old token immediately; replace `dashboard_token` and restart the game server.

## Enable remote controls deliberately

The native plugin defaults to local-only control. After its first run, edit the generated `oniprofiler.toml` in the plugin data folder:

```toml
remote_controls_enabled = true
remote_management_enabled = false
```

Restart to apply external file edits. The first option allows authorized operators to request health snapshots, scans and guided recordings. The second additionally allows managers to change monitoring policies and request the advanced memory preset. Both local policy and dashboard access are checked.

Remote stop/discard requests identify the exact active session. Operators can stop their own remote session; locally initiated or other owners' sessions require a manager and the local management gate. Requests expire after two minutes and target one plugin boot identity. Queued, applied, rejected, expired and indeterminate states are separate. A stop acknowledgement means the export was requested; a completed report is the evidence that saving finished.

## Reports, shares and storage

JSON report synchronization is enabled by default for the native link. Raw `.sparkprofile` files stay local because they can contain player names, paths and server metadata. The optional external Python agent is still available on hosts that deliberately want local native-profile analysis, raw-profile upload, cgroup/Pterodactyl context or runtime-source forwarding; none of those extras are required to link a normal Endstone server.

Shared reports are read-only, expiring and revoked individually. They exclude names, notes, native payloads, owner/session identity and coordinates by default. Coordinates require explicit approval on share creation. Anyone possessing a live share URL can read that shared view; send it accordingly.

Default limits: 500 reports per server, 24 hours of history, a 2 MiB JSON body limit, a 64 MiB native-profile limit and a 2 GiB combined native-profile quota. Plugin-side local retention is configured separately. Application audit storage is bounded. Backup the SQLite database with `oniprofiler-admin backup <destination>` and copy the profile directory under controlled conditions; the database backup alone does not contain native profile files.

## Optional hosting context and notifications

The optional external agent can read a specifically configured cgroup v2 directory. It never assumes its own container is the game server's container. Pterodactyl integration uses the **Client API resources endpoint only**; set `panel_url`, `panel_server`, and supply the API key through `ONI_PANEL_TOKEN`. Use the least-privileged dedicated panel account available. Polling is limited to once per minute. No arbitrary console access is added.

The central service accepts `ONI_DISCORD_WEBHOOK` for incident notifications to an official Discord webhook. It uses a bounded queue, no mentions and reduced context. The webhook remains server-side. A real Discord/Pterodactyl deployment was not tested here.

## Optional legacy/advanced external agent

The bundled Python agent and startup wrapper are only for deployments that explicitly need the advanced host/profile features above and have Python available. They are not part of normal game-server installation. Where your host permits that optional setup:

```bash
oniprofiler-launch --agent-config /home/container/agent.toml -- ./bedrock_server
```

Replace `./bedrock_server` with your **existing Endstone/Onistone startup executable and arguments**, not a guessed loader command. The wrapper does not invoke a shell, forwards shutdown signals, and does not kill the Minecraft process merely because the agent fails. A Python-aware custom image or host-side agent is required if the existing image lacks Python. No new player-facing port is needed. Do not expose agent credentials through public startup logs.

## Local development only

```bash
export ONI_PUBLIC_ORIGIN=http://127.0.0.1:8080
export ONI_ALLOW_HTTP_LOOPBACK=1
oniprofiler-server --allow-http-loopback
```

The explicit development mode may only bind loopback. Never put this mode on a public address. GitHub Pages serves only the separate offline viewer, not this authenticated API.
