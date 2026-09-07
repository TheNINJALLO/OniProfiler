# Configuration

OniProfiler stores its files under `plugins/oniprofiler/`. Existing
`plugins/spark/` files are never imported, edited, moved or deleted automatically.
`oniprofiler.toml` belongs to the control center. `config.toml` remains Spark's
engine configuration. The OniProfiler background policy takes precedence over
the engine's initial background-enabled value. Broadcasts of native export
responses are disabled by this plugin so URLs and file paths are not broadcast
to unrelated staff.

Default `oniprofiler.toml`:

```toml
remote_controls_enabled = false
remote_management_enabled = false
background_enabled = true
incidents_enabled = true
automatic_profiles = false
allow_external_sharing = false
refresh_seconds = 5
area_cooldown_seconds = 60
max_areas = 200
retained_summaries = 100
automatic_storage_limit_mb = 256
incident_threshold_ms = 100
incident_sustain_seconds = 5
incident_cooldown_seconds = 300
```

An incident requires **consecutive observed ticks** lasting at least the threshold
for the sustained wall-clock duration. One healthy/invalid observation resets the
streak. This detector is deliberately conservative; it does not catch every form
of intermittent lag or a deadlocked server with no new tick observations. Spark's
separate native recovery/watchdog mechanisms remain in the engine.

`automatic_profiles` is opt-in because a new recording replaces background
sampling. A qualifying incident starts a 60-second local profile only when no
foreground recording/export is active and the last measured native-profile
storage is below the budget. This is **a start guard, not a hard disk quota**:
measurements are periodically refreshed, an ongoing recording can exceed the
budget, manual recordings are not blocked, and recovery journals are not included
in that byte count. Manage disk capacity independently.

`retained_summaries` prunes only OniProfiler-managed `report-*.json` summaries.
Native `.sparkprofile` files are **never automatically deleted**. `dashboard.json`
is replaced with the latest snapshot. The report worker has a 32-entry queue and
coalesces dashboard writes; the server log reports failures and no disk-write
success is claimed just because a report was queued.

The in-game settings menu updates the background, incident, and automatic-profile
booleans. Other settings, including external sharing, require editing the managed
TOML and restarting. The settings writer rewrites this small managed file, so
personal comments in it are not preserved. Spark's own config is not rewritten by
those toggles. Invalid TOML or invalid value types/ranges cause startup to fail
without replacing the invalid file.

The new remote-control booleans require an owner edit and restart. They cannot be enabled from the dashboard. The default outbound-agent interval is five seconds and the service refuses control requests against stale plugin snapshots. See DASHBOARD.md for enrollment and command acknowledgements.
