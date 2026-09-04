# Libas — commands reference

`docker compose up -d` (from `db/`) now starts EVERYTHING backend-side —
Postgres, Grafana, and the FastAPI API itself. See `db/scraper/COMMANDS.md`
for the scraping pipeline and `db/`'s one-off maintenance scripts — this
file covers the app: backend, frontend, CLI.

## Backend (FastAPI, dockerized)

```powershell
cd db
docker compose up -d          # postgres + grafana + api, all three
docker compose logs -f api    # tail the API's logs (it runs uvicorn --reload inside)
docker compose restart api    # rarely needed — --reload already picks up .py edits live
```

`server/` is bind-mounted into the container, so editing any `.py` file
locally takes effect immediately (uvicorn's `--reload` runs *inside* the
container, watching the mounted volume) — no rebuild needed for code
changes. A rebuild (`docker compose up -d --build api`) is only needed
after changing `server/requirements.txt`.

Runs on port 4000, same as before — no frontend config changes.

**Not dockerized on purpose:** the CLI (`cli.py`, below) — it's an
interactive debug tool, not a long-running service, and needs a real
TTY for its gender prompt. Run it locally with your own Python/pip:

```powershell
cd server
pip install -r requirements.txt   # one-time, only needed for the CLI
```

## Frontend (Vite + React)

```powershell
cd frontend
npm run dev          # expects the backend already running via docker compose (above)
```

`npm run dev:api` / `npm run dev:all` still exist (bare `uvicorn`, no
Docker) as a fallback for working on the API without Docker running —
just don't run both that AND the dockerized `api` service at once, they'd
fight over port 4000.

## CLI (search pipeline debug tool)

Prints every stage — the raw LLM tool-call arguments, each retrieval leg's
ranked titles, and the final RRF-fused result:

```powershell
cd server
python cli.py "furor jeans"
python cli.py "cozy warm sweaters for women under 5000"
python cli.py "kurta set under 3000" --gender=3    # skips the interactive prompt (1=Men 2=Women 3=Boys 4=Girls)
```

## Monitoring

- Grafana: `http://localhost:3001`, login `admin`/`admin`. Dashboard
  "Libas Search Quality" is already provisioned (datasource + dashboard
  both load automatically from `db/monitoring/grafana/` — nothing to
  click through manually). Empty until real searches happen.
- Every `/api/search` call writes one row to `search_logs` in the same
  Postgres database — query text, resolved filters, latency, token
  counts, estimated OpenAI cost. See `server/db_conversations.py`.

## Production access (Grafana + DB, no SSH)

The prod EC2 instance has no SSH key and no open port besides 80/443 — it's
administered entirely through AWS SSM. `scripts/prod-tunnel.ps1` opens a
local port forward over that same SSM channel (one-time setup: `winget
install Amazon.SessionManagerPlugin`):

```powershell
./scripts/prod-tunnel.ps1 -Target grafana   # -> http://localhost:3001 (user=admin, password NOT the local-dev default)
./scripts/prod-tunnel.ps1 -Target db        # -> localhost:5433 (db=libas, user=libas)
```

Leave it running in its own terminal; `Ctrl+C` closes the tunnel. Neither
password lives in this repo — pull them fresh when needed:

```powershell
aws ssm send-command --instance-ids i-03771ac3d2f76e37d --document-name AWS-RunShellScript `
  --parameters 'commands=["docker exec libas-postgres env | grep POSTGRES_PASSWORD"]'
# swap the container/grep for libas-grafana / GF_SECURITY_ADMIN_PASSWORD for the Grafana one
# then: aws ssm get-command-invocation --command-id <id-from-above> --instance-id i-03771ac3d2f76e37d --query StandardOutputContent --output text
```

**Known flaws — verified against this account, not hypothetical:**
1. **IAM credentials gate this, not a dedicated key.** A leaked `cli-deploy`
   access key gives immediate tunnel access to prod Grafana and Postgres —
   there's no separate secret to also compromise, unlike an SSH key.
2. **Password reuse across services**: prod Grafana's admin password and
   the Postgres password are the literal same string. One leak compromises
   both — Grafana should have its own independent secret.
3. **No CloudTrail trail exists in this account at all** (`aws cloudtrail
   describe-trails` returns empty) — not just "SSM sessions aren't logged,"
   *nothing* is. No audit record of who tunneled in, when, or from where,
   and no record of any other AWS API activity either.
4. **`cli-deploy` has full `AdministratorAccess`**, far broader than
   "start a Grafana/DB tunnel" needs — a scoped-down policy would contain
   the blast radius of a leaked key instead of handing over the whole
   AWS account.
5. **The mechanism itself is a documented attacker technique**: SSM port
   forwarding is outbound-only and looks like ordinary AWS API traffic to
   most network monitoring, which is exactly why threat actors abuse it for
   covert lateral movement once they have IAM credentials — see
   [Palo Alto Networks: Living Off the Cloud](https://www.paloaltonetworks.com/blog/security-operations/aws-systems-manager-attack-vectors/)
   and [100 Days of Red Team: Ghost in the Cloud](https://www.100daysofredteam.com/p/ghost-in-the-cloud-abusing-aws-ssm).
   This isn't a reason not to use it here, but it means the *only* thing
   standing between "convenient admin access" and "silent backdoor" is
   how well the IAM credentials are protected.

## Health check

```powershell
curl http://localhost:4000/api/health
```

## Known, still-open (not bugs introduced by anything above)

- Color filtering under-recalls ~40% on average (no normalization/alias
  table yet — see `server/SEARCH.md`).
- A bare-text "kids" query with no explicit Boys/Girls resolves too
  narrowly (schema has no combined-kids gender value) — the frontend's
  Kids-mode toggle already works around this for UI-driven searches.
- OpenTelemetry is planned, not built — Postgres + Grafana only for now
  (see the marker comment in `server/main.py`'s `lifespan`).
