# Private live dashboard and outbound agents

The native plugin works without a dashboard. For the combined system, run one central dashboard and one agent per Minecraft server. Agents read the plugin's timestamped telemetry and reports, synchronize them over verified HTTPS, and deliver a fixed set of profiler requests through a private local mailbox. They never expose a network listener on a Minecraft server.

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

Install the included `oniprofiler_control-1.0.0rc2-py3-none-any.whl` into Python 3.11+ in a virtual environment. This is an external dashboard/agent package, not the game plugin, and must not be placed in the Endstone `plugins/` directory. Alternatively install `./controlplane` from source:

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

Sign in, open **Access & settings**, create the server and copy its one-time agent token. Never paste an administrator session or an application-wide credential into a game add-on.

Install the control-plane wheel on the game-server host or container. Copy `deploy/agent.example.toml` to a **private** `agent.toml`. Set the dashboard origin, the actual OniProfiler data folder and a unique writable agent-state folder. The plugin data folder is normally `plugins/oniprofiler`; confirm it on your installed Endstone/Onistone build.

Save the raw agent token, without a `Bearer` prefix, in the configured owner-only token file. On Linux set `chmod 600`. Run the agent as the same operating-system user as the game server or deliberately provision the mailbox permissions. Do not make the plugin folder world-writable.

```bash
oniprofiler-agent --config /srv/bedrock/agent.toml
```

Create a **separate state directory for each server**. Re-enrolling into a different dashboard/server requires a new state directory. Agent-token rotation invalidates the old token immediately; update its private file and restart the agent.

## Enable remote controls deliberately

The native plugin defaults to local-only control. After its first run, edit the generated `oniprofiler.toml` in the plugin data folder:

```toml
remote_controls_enabled = true
remote_management_enabled = false
```

Restart to apply external file edits. The first option allows authorized operators to request health snapshots, scans and guided recordings. The second additionally allows managers to change monitoring policies and request the advanced memory preset. Both local policy and dashboard access are checked.

Remote stop/discard requests identify the exact active session. Operators can stop their own remote session; locally initiated or other owners' sessions require a manager and the local management gate. Requests expire after two minutes and target one plugin boot identity. Queued, applied, rejected, expired and indeterminate states are separate. A stop acknowledgement means the export was requested; a completed report is the evidence that saving finished.

## Reports, shares and storage

JSON report synchronization is enabled by default for an enrolled agent. Native analysis is derived locally from available immutable `.sparkprofile` files. Uploading the raw profile is a separate explicit `sync_native_profiles = true` setting. Native files can contain player names, paths and server metadata, so treat them as private diagnostic data.

Shared reports are read-only, expiring and revoked individually. They exclude names, notes, native payloads, owner/session identity and coordinates by default. Coordinates require explicit approval on share creation. Anyone possessing a live share URL can read that shared view; send it accordingly.

Default limits: 500 reports per server, 24 hours of history, a 2 MiB JSON body limit, a 64 MiB native-profile limit and a 2 GiB combined native-profile quota. Plugin-side local retention is configured separately. Application audit storage is bounded. Backup the SQLite database with `oniprofiler-admin backup <destination>` and copy the profile directory under controlled conditions; the database backup alone does not contain native profile files.

## Optional hosting context and notifications

The agent can read a specifically configured cgroup v2 directory. It never assumes its own container is the game server's container. Pterodactyl integration uses the **Client API resources endpoint only**; set `panel_url`, `panel_server`, and supply the API key through `ONI_PANEL_TOKEN`. Use the least-privileged dedicated panel account available. Polling is limited to once per minute. No arbitrary console access is added.

The central service accepts `ONI_DISCORD_WEBHOOK` for incident notifications to an official Discord webhook. It uses a bounded queue, no mentions and reduced context. The webhook remains server-side. A real Discord/Pterodactyl deployment was not tested here.

## Pterodactyl startup wrapper

Where the Python wheel is installed in the same container and your host permits startup customization:

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
