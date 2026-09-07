# Privacy and sharing

The normal guided path saves native profiles and JSON summaries locally. The
viewer parses user-selected JSON in browser memory; it does not upload reports,
run analytics, save data to localStorage, automatically follow report URLs, or
connect to a Minecraft server. Its content security policy blocks fetch/network
connections. A Pages deployment serves the UI assets, not the imported files.

Native profiles can contain sensitive metadata such as server configuration,
software/plugin details, usernames and world coordinates. JSON summaries can
contain recording owners, loaded-area coordinates, entity counts and native
report paths/URLs. They are **not automatically anonymized**. Inspect content
before copying it to chat, issue trackers, support staff or external viewers.

`allow_external_sharing = false` is the default. Opening Spark's live viewer
requires enabling that configuration, restarting, obtaining the sharing
permission and approving the in-game disclosure. Explicit advanced commands are
an alternative approval path and retain their native permissions. Starting/stopping
through the compatibility layer defaults to local files, including legacy stop
aliases. External health-report `--upload` is gated as well.

Spark's configured bytebin/viewer/socket services are external services. Do not
represent approval as a promise that those third-party services have any specific
retention, anonymity or security policy. Trusted viewers remain in the local
`trusted-viewers.json` maintained by Spark.

A standalone static web server should serve only `web/`, bound to loopback. Do
not expose the server's `plugins`, worlds, profile, recovery or configuration
folders. No server passwords, API tokens, or credentials are needed by this
offline viewer or should be committed to the repository.


## Live dashboard

The private live dashboard is a separate surface with an authenticated backend; its connections are intentional. Enrolling an agent enables synchronization of JSON reports into that private service. Native file uploads require additional opt-in. Therefore the offline viewer's "no upload" property must not be applied to the live service.

Expiring public-share snapshots use an allowlisted reduced schema, excluding identities, private notes, raw profiles and native paths. Coordinates are omitted unless explicitly included. These links remain bearer capabilities until revoked/expired. The full report remains private. Read DASHBOARD.md and SECURITY.md for token, backup and proxy-log guidance.
