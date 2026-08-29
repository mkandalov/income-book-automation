# Internal HTTPS deployment

The application is deployed with Docker Compose on an internal Linux VM:

```text
employee browser -> HTTPS :443 -> Caddy -> HTTP app:8000
```

Caddy is the only public entry point. The FastAPI port is published on
`127.0.0.1` for local diagnostics and cannot be reached directly from another
computer.

## Production configuration

Create `.env` next to `compose.yaml`. Do not commit this file:

```dotenv
INCOME_BOOK_HOST=10.100.0.221
INCOME_BOOK_PORT=8000
INCOME_BOOK_CLIENTS_HOST_DIR=/srv/income-book/clients
IMAGE_TAG=0.1.0
```

`INCOME_BOOK_HOST` must be the exact IP address or internal DNS name employees
use in the browser. Caddy includes this value in the generated certificate.

Client YAML profiles remain outside both Git and the Docker image. Compose
mounts their host directory read-only at `/data/clients`.

## First start

```bash
cd /opt/income-book/app
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
curl --insecure --fail https://10.100.0.221/health
```

`--insecure` is acceptable only for this first technical check, before the
internal root certificate is trusted by the operating system.

## Trusting the internal certificate

Caddy stores its private certificate authority in the persistent `caddy_data`
volume. Export only the public root certificate:

```bash
mkdir -p /srv/income-book/tls
docker compose cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  /srv/income-book/tls/caddy-root.crt
openssl x509 \
  -in /srv/income-book/tls/caddy-root.crt \
  -noout -subject -fingerprint -sha256
```

An administrator must install `caddy-root.crt` into the trusted root
certificate store of the employee machines. The fingerprint should be checked
before installation. The private CA key must never be copied from the Docker
volume.

After installation, open `https://10.100.0.221` and verify that the browser no
longer displays a certificate warning.

## Updating the application

```bash
cd /opt/income-book/app
git pull --ff-only
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail https://10.100.0.221/health
```

If the internal certificate is not trusted in the administrator's shell yet,
use `curl --insecure` for the last diagnostic command only.

## Important operational rules

- Do not run `docker compose down -v`. The `-v` option deletes Caddy's internal
  certificate authority and would require installing a new root certificate on
  every employee machine.
- Back up `/srv/income-book/clients` separately from the application code.
- Keep `.env`, client profiles, generated workbooks, certificates, and private
  keys outside Git.
- Restrict inbound firewall access to the networks that need HTTPS. SSH should
  remain limited to administrators.
- HTTPS encrypts traffic but does not authenticate users. Application login and
  authorization are a separate future feature.

## Diagnostics

```bash
docker compose ps
docker compose logs --tail 100 app
docker compose logs --tail 100 caddy
curl --fail http://127.0.0.1:8000/health
```

Both services should report `healthy`. VM snapshots provide the infrastructure
rollback point; Git provides the application-code history.
