# Permissions and recording ownership

All of these default to operators. Grant non-operators only the capabilities
needed for their role. `oniprofiler.view` is the entry permission for commands and
forms, but does not itself grant recording, coordinates, sharing or management.

| Permission | Capability |
| --- | --- |
| `oniprofiler.view` | Open forms and read aggregate health/status. |
| `oniprofiler.record` | Start guided execution recordings and control recordings owned by that player. |
| `oniprofiler.reports` | Browse native report locations and queue JSON health exports. Treat this as sensitive access. |
| `oniprofiler.locations` | Request/read loaded-area coordinates and entity breakdowns. |
| `oniprofiler.manage` | Change supported settings, control other owners' sessions, and stop/cancel background sessions. |
| `oniprofiler.advanced` | Use advanced `/spark` commands; required alongside record permission for allocation presets. |
| `oniprofiler.share` | Explicitly open external viewing when server configuration also permits it. |
| `oniprofiler.alerts` | Receive sustained-incident notifications. |

Advanced commands additionally pass Spark's own registry permissions:
`spark.profiler`, `spark.tps`, `spark.ping`, `spark.health`, `spark.activity`, and
`spark.tickmonitor`. `endstone.command.spark` remains registered for compatibility.
Guided forms call the native service after OniProfiler permission checks, rather
than requiring users to have every legacy Spark command permission.

A viewer form does not confer enduring authorization. Callbacks recheck
permissions, validate selection bounds, and reject controls for a changed native
session. The name of the authenticated command sender identifies the owner of a
foreground session; a manager can override ownership. Profile access is not a
per-player confidentiality boundary once someone has server filesystem access.

JSON exports contain a combined snapshot, including retained loaded-area data and
native report references. Do not grant report/export or filesystem access to
staff who should not see those details. The offline viewer has no authentication
layer because files are explicitly supplied by their holder; it is not a public
report-hosting service.


The live dashboard uses separate authenticated server grants: viewer, operator and manager. Those are not Minecraft OP status or an automatic mapping of in-game permission strings. Administrators are fleet-wide. Local `remote_controls_enabled` and `remote_management_enabled` must additionally permit the action. Runtime-only keys cannot read or control the server. Review these roles independently when enrolling staff.
