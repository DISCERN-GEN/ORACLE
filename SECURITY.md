# Security Baseline

1. Keep `.env` out of source control and backups must be encrypted.
2. Change all example passwords and API tokens before running the platform.
3. Keep database and dashboard ports bound to loopback for the initial private deployment.
4. Do not expose the FastAPI service or dashboard directly to the public internet.
5. Do not put signing keys, seed phrases, private wallet material or trading credentials into the agent, API, dashboard, notebooks or logs.
6. v0.2 contains no signing implementation and no live order submission route.
7. A future signing gateway must be isolated from the agent process, use least privilege and require independent policy validation.
8. Geoblock or local legal restrictions must never be bypassed with VPNs, proxies or location spoofing.
9. Audit data is append-only at the database level; protect database credentials and verify the hash chain before relying on the trail.
10. Test backups and restore procedures before beginning a 12-hour acceptance run.
