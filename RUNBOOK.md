# StudioOS runbook

> DRAFT for the owner to confirm. Assembled from `compose.yaml`, the scripts in `ops/` and the env examples. It was
> not tried on the real server. Anything marked **Confirm** needs the person who runs the server to check it.

## Two copies, kept apart
There is a **live** copy and a **test** copy (separate database, containers and backups). Always try a change on the
test copy first. Use the scripts in `ops/`; add `--test` to work on the test copy.

| Task | Command |
| --- | --- |
| Start or restart | `ops/start.sh` |
| See containers, newest backups and safety status | `ops/status.sh` |
| Verified backup now (then a test restore) | `ops/backup-now.sh [label]` |
| Upgrade to the version in `VERSION` (test copy first) | `ops/upgrade.sh --test`, then `ops/upgrade.sh` |
| Go back to an earlier version | `ops/rollback.sh --to <version>` |
| Refresh the test copy from the newest live backup (personal details masked) | `ops/make-test-copy.sh` |

Upgrades take a labelled backup first and switch back automatically if the health check fails. Database changes are
additive only, so switching back keeps all data.

## Settings that matter (env file)
- `STUDIOOS_TRUSTED_PROXIES`: the addresses or ranges of any proxy in front of StudioOS (for example `10.0.0.1,192.0.2.0/24`).
  The forwarded caller address is believed only when the request came from one of these. Leave empty if nothing sits in front.
  **Confirm on the NAS test copy.** Find the address the StudioOS container actually sees for Tailscale. Docker can show a different address from the NAS. List only the proxy address you verified. With a listed proxy, two phones using different Tailscale addresses should have separate failed sign-in limits. Try one wrong sign-in on each phone using two fictional usernames with `STUDIOOS_LOGIN_MAX_PER_IP=1` on the test copy. Restart the test copy after changing these settings. Both phones should get “Invalid username or password.” Once the 15-minute window has passed, repeat with the list empty. If both phones now arrive through the same Docker address, the second phone should get “Too many failed sign-ins.” Restore the original test settings afterward.
- `STUDIOOS_2FA_KEY_FILE`: production requires the key file that encrypts two-factor secrets. Keep it **outside** the database and the backups.
  - The owner chose a NAS folder outside `BACKUP_PATH` and `OFFSITE_PATH`. Set `TWOFA_KEY_DIR` to that folder and `STUDIOOS_2FA_KEY_FILE=/secrets/twofa.key` in the env file; compose.yaml mounts the folder read-only at `/secrets`.
  - Create once, with the app stopped: `python -m studioos.encrypt_2fa --create-key /secrets/twofa.key` (run it in a one-off container with the folder mounted writable, or create the file on the NAS and set it to mode 600).
  - Encrypt secrets already stored: `python -m studioos.encrypt_2fa`.
  - The owner holds the **separate recovery copy** (USB drive or password manager, away from the NAS). Without it encrypted secrets cannot be read, and each person sets up two-factor again
    (the owner can reset it from the server). **Confirm** the folder path on the NAS.

## Test the public connector address

- On the test copy, enable the optional Docker connector service with `COMPOSE_PROFILES=connector ops/start.sh --test`. The service listens on the NAS itself. The examples use port 8002 for the live copy and 8003 for the test copy. Set `STUDIOOS_CONNECTOR_PORT` to a free port for your copy. Use the same `COMPOSE_PROFILES=connector` setting when upgrading a copy that runs the connector.
- Point the public connector address to that dedicated port. Keep the normal StudioOS address private. If you already use a public WhatsApp webhook, keep its routing separate from the connector.
- **Confirm on the NAS test copy.** Use the connector’s existing sign-in key to check that `/mcp` works through the public address. Open the root address and `/api/auth/login` through the same public route. Both should say “Not found.” From the NAS itself, repeat those checks against the dedicated port with the public name without its port and with another name in the request’s Host header. Both names should give the same result.
- Each Docker service keeps up to three log files of 10 MB each. After a backup attempt fails, check **Data safety** and `ops/status.sh --test` for “Latest backup failed.” A verified backup clears the warning.

## Running as a non-root user
The app image now runs as user id 10001, not root. Folders the app writes to (`BACKUP_PATH`, `FILES_PATH`, and the offsite
folder for the backup service) must be writable by that id, for example `chown -R 10001:10001 <folder>` on the NAS.
The owner will set the owner of these folders to 10001 (`chown -R 10001:10001`). Do it on the test copy first; a folder that is not writable shows up as a failed start or a failed backup.
Build with other ids if the NAS needs them: `--build-arg STUDIOOS_UID=<id> --build-arg STUDIOOS_GID=<id>`.

## Pinned packages
`constraints.txt` fixes the exact version of every direct requirement. Update it on purpose, in a pull request, and run the
full tests and the test-copy upgrade before a release.

## Recovery
- Database back to a backup: `ops/rollback.sh --restore-db <file>`. The current database is renamed and kept, never deleted.
- Forgot the owner's two-factor device: run the server-side recovery command (`python -m studioos.recover_admin --disable-2fa`), which is audited.
- Attached files come back from the backup folder; the app only reads the NAS project folders and never changes them.
