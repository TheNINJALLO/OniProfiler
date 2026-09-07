# Security and diagnostic boundaries

Treat native profilers as privileged server software. Stage changes before a live world and never run this plugin alongside another copy of Spark's native sampler.

The dashboard requires a local bootstrap account, HTTPS, secure HttpOnly SameSite session cookies and same-origin CSRF checks. Server grants distinguish viewer, operator and manager; administrators are intentionally fleet-wide. Server-link tokens, runtime write-only keys and share tokens are independently scoped and stored hashed by the dashboard. The native plugin keeps its server token in the managed config and restricts that file to the server account on Linux. Do not log tokens or put credentials into source control.

Remote controls are disabled locally by default. Both the service and native bridge use an explicit action allowlist. There is no arbitrary console-command endpoint, remote shell, plugin installer or automatic entity deletion. Commands expire and identify one plugin instance and, where relevant, one recording session. An interrupted claimed command becomes indeterminate instead of being replayed.

The local mailbox is a trusted operating-system boundary, not a defense against another plugin running as the same user. Such a plugin can access the game process already. Restrict directory ownership, reject symlink files and protect backups. The native connector permits HTTPS only, verifies certificates, refuses redirects and bounds request/response sizes. The web service cannot make untrusted native code safe.

Snapshots and raw profiles can reveal world locations, names, paths and configuration. The native connector can synchronize private JSON reports; raw profiles remain local unless the optional external agent is deliberately configured to upload them. Share creation uses an allowlisted reduced schema with coordinates excluded by default. Share links remain bearer capabilities until expiry/revocation. Avoid sharing them through public logs.

Limits and authorization checks are tested but this is not a penetration-test certification. Review TLS deployment, proxy logging, dependencies, backups and retention in your environment. Report vulnerabilities privately to the repository owner before publicly disclosing sensitive details. Do not upload a real token or private profile in an issue.
