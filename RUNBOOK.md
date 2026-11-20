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
  **Confirm** what sits in front (Tailscale, Nginx, Cloudflare).
- `STUDIOOS_2FA_KEY_FILE`: path to the key that encrypts two-factor secrets. Keep it **outside** the database and the backups.
  - Create once: `python -m studioos.encrypt_2fa --create-key /path/twofa.key`, then mount that folder into the app container.
  - Encrypt secrets already stored: `python -m studioos.encrypt_2fa`.
  - Keep a **separate recovery copy** of the key. Without it encrypted secrets cannot be read, and each person sets up two-factor again
    (the owner can reset it from the server). **Confirm** where the key file lives and who holds the recovery copy.

## Running as a non-root user
The app image now runs as user id 10001, not root. Folders the app writes to (`BACKUP_PATH`, `FILES_PATH`, and the offsite
folder for the backup service) must be writable by that id, for example `chown -R 10001:10001 <folder>` on the NAS.
**Confirm** this on the test copy first; a folder that is not writable shows up as a failed start or a failed backup.
Build with other ids if the NAS needs them: `--build-arg STUDIOOS_UID=<id> --build-arg STUDIOOS_GID=<id>`.

## Pinned packages
`constraints.txt` fixes the exact version of every direct requirement. Update it on purpose, in a pull request, and run the
full tests and the test-copy upgrade before a release.

## Recovery
- Database back to a backup: `ops/rollback.sh --restore-db <file>`. The current database is renamed and kept, never deleted.
- Forgot the owner's two-factor device: run the server-side recovery command (`python -m studioos.recover_admin --disable-2fa`), which is audited.
- Attached files come back from the backup folder; the app only reads the NAS project folders and never changes them.
