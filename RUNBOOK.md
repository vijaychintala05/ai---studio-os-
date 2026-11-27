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

## Client portal (draft; nothing here was run on the NAS)
Clients get a page of their own per project, for example `sharma.portal.yourstudio.com`. They see only what staff share with them (files,
what was agreed, messages). **Staff keep using StudioOS over Tailscale; only the portal listener faces the internet.**

**What you set up (once)**
1. **A name.** Pick a portal domain you own, for example `portal.yourstudio.com`. In your DNS add one wildcard record `*.portal.yourstudio.com` that points to the machine that runs the reverse proxy (step 3).
2. **A certificate** for `*.portal.yourstudio.com` (a wildcard certificate). Most DNS hosts and tools like Caddy or Let's Encrypt can renew it automatically using a DNS-provider key.
3. **A reverse proxy** (Caddy, Nginx or Cloudflare Tunnel) that accepts `*.portal.yourstudio.com` over HTTPS and sends it, keeping the original Host name, to the portal listener on the NAS: `127.0.0.1:${STUDIOOS_PORTAL_PORT}` (default 8004). Do not point any other name at this listener.
4. **Settings in the env file:** `STUDIOOS_PORTAL_DOMAIN=portal.yourstudio.com`, `STUDIOOS_PORTAL_PEPPER` (32+ random characters; the portal refuses to run live without it), `STUDIOOS_SECURE_COOKIE=true`, and `STUDIOOS_TRUSTED_PROXIES` set to your reverse proxy's address so sign-in limits count the real client, not the proxy.
5. **Start the listener:** `COMPOSE_PROFILES=portal ops/start.sh --test` on the test copy first. The normal StudioOS address stays private.
6. **Sign-in codes.** Choose how codes reach clients (`STUDIOOS_PORTAL_SENDER`):
   - `smtp`: email through any mail service you already use. Set `STUDIOOS_PORTAL_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`.
   - `webhook`: SMS or WhatsApp through your provider. StudioOS sends one signed HTTPS request per code to `STUDIOOS_PORTAL_WEBHOOK_URL` with `STUDIOOS_PORTAL_WEBHOOK_TOKEN` as a Bearer token, and your provider (or a small automation) turns it into a message. The body is `{"to": "<phone or email>", "via": "phone|email", "text": "..."}`.
   - Keep passwords and tokens in the env file only. Never put them in chat, email or the repository.

**Confirm on the NAS test copy (not done by the agent)**
- Open `https://<project>.portal.yourstudio.com/` from a phone off your Wi-Fi: you should see the "Welcome" sign-in page and nothing about the project.
- Open `https://portal.yourstudio.com/`, `https://<project>.portal.yourstudio.com/api/auth/login` and `/docs`: all must say "Not found".
- Ask for a code and check it arrives; try a wrong code five times and check the code stops working.
- Sign in as a client of project A; then open project B's address in the same browser: you must be asked to sign in again.
- After a staff member switches a contact off, that client's open page must stop working on the next tap.
- Check `ops/status.sh --test` still shows healthy backups; the portal tables are included automatically (they are ordinary tables).

**Setting up a project's portal (staff, in StudioOS)**: open **Projects**, open the project, and scroll to its **Client portal** section (or tap the Client portal chip at the top of the page). As the owner, open the Setup tab and set the address name (for example `sharma`), add the client's phone or email, then share files and write up conversations. Everything a client sees is something a person chose to share.

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

## Local checks and promotion through `dev`

Use a WSL2 Ubuntu checkout in the Linux filesystem. Install the versions used by
[CI](.github/workflows/ci.yml) (Python 3.12 and Node 22), Gitleaks 8.19 or later,
Docker with local WSL integration, PostgreSQL 16 client tools, Tesseract, and
Poppler. Activate a virtual environment and install dependencies with
`python -m pip install -r sim/requirements.txt -c constraints.txt`.

In the WSL clone, run `git config --get core.hooksPath` before installing the
optional hook so you can preserve any existing hooks. Set
`git config --local core.hooksPath .githooks` to use this repository's hook.
It scans the outgoing commits, checks page scripts, and runs added or changed
test files. Include other focused tests with
`git config --local --add studioos.pushTest tests/test_example.py`, replacing
the example path with a real test in the branch. You can also run
`bash ops/local-check.sh --quick -- tests/test_example.py` by hand.

1. Work on a task branch from `dev`. Commit the changes and run
   `bash ops/local-check.sh`. It checks the committed snapshot in temporary
   storage and creates its own PostgreSQL 16 container and test databases.
2. Once the local checks pass and Vijay reviews the diff, Vijay merges the
   task branch into `dev` with `--no-ff` and pushes `dev`.
3. In GitHub Actions, verify that all five jobs succeeded for the exact
   `dev` commit being promoted. Vijay pushes that verified SHA with
   `git push origin <verified-sha>:refs/heads/main`. Git rejects a non-fast-forward
   push. If `main` advanced independently, update `dev` and rerun its checks.
4. Record what changed, why, what passed, and anything left untested in the
   task handoff. Before integrating, check project access, ticket approval,
   additive migrations, and money in integer paise when relevant.

**First-time activation.** Land the workflow update through the current
pull-request process. Create `dev` from the updated `main` and verify a
successful push-triggered run. In GitHub's protection settings for `main`,
require all five checks from GitHub Actions and keep force pushes and deletion
disabled. Remove the pull-request requirement only when Vijay is ready to use
the new workflow. Keep the existing workflow until the protection rules and a
trial promotion have been verified.
