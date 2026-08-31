# Docker deployment

The preferred production topology uses the reverse proxy that already exists
in the infrastructure:

```text
employee browser -> HTTPS -> infrastructure reverse proxy
                 -> HTTP VM_PRIVATE_IP:8000 -> FastAPI
```

The reverse proxy owns the employee-facing domain, TLS certificate, automatic
certificate renewal, and HTTPS security policy. The application VM exposes
only its private HTTP endpoint to that proxy.

Caddy remains available as an optional Docker Compose profile for standalone
networks that do not already have a reverse proxy.

## Production configuration

Create `.env` next to `compose.yaml`. Do not commit this file:

```dotenv
INCOME_BOOK_BIND_ADDRESS=10.0.0.10
INCOME_BOOK_PORT=8000
INCOME_BOOK_HOST=localhost
INCOME_BOOK_CLIENTS_HOST_DIR=/srv/income-book/clients
IMAGE_TAG=0.1.0
```

Replace `10.0.0.10` with the VM's actual private IP address. Do not use
`0.0.0.0` unless a firewall explicitly limits access to trusted networks.
`INCOME_BOOK_HOST` is ignored unless the optional Caddy profile is enabled.

Client YAML profiles remain outside both Git and the Docker image. Compose
mounts their host directory read-only at `/data/clients`.

## First start behind an infrastructure reverse proxy

```bash
cd /opt/income-book/app
docker compose config --quiet
docker compose up -d --build app
docker compose ps
curl --fail http://10.0.0.10:8000/health
```

Replace the example IP in the health check with the value configured in
`INCOME_BOOK_BIND_ADDRESS`. The application should report `healthy`, and the
health endpoint should return `{"status":"ok"}`.

The reverse-proxy administrator must then:

1. Point the internal domain at the infrastructure reverse proxy.
2. Configure HTTPS and automatic certificate renewal.
3. Forward requests to `http://VM_PRIVATE_IP:8000`.
4. Restrict direct access to port 8000 to the reverse proxy or trusted internal
   network.

## Optional standalone HTTPS with Caddy

For an environment without an existing reverse proxy, keep the application
bound to loopback and enable the `internal-https` profile:

```dotenv
INCOME_BOOK_BIND_ADDRESS=127.0.0.1
INCOME_BOOK_HOST=10.0.0.10
```

```bash
docker compose --profile internal-https up -d --build
docker compose ps
curl --insecure --fail https://10.0.0.10/health
```

`--insecure` is acceptable only for the first technical check. Caddy stores its
private certificate authority in the persistent `caddy_data` volume. Export
only the public root certificate when client devices need to trust this CA:

```bash
mkdir -p /srv/income-book/tls
docker compose cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  /srv/income-book/tls/caddy-root.crt
openssl x509 \
  -in /srv/income-book/tls/caddy-root.crt \
  -noout -subject -fingerprint -sha256
```

The private CA key must never be copied from the Docker volume.

## Updating the application

```bash
cd /opt/income-book/app
git pull --ff-only
docker compose config --quiet
docker compose up -d --build app
docker compose ps
curl --fail http://10.0.0.10:8000/health
```

Replace the example IP with the VM's private IP. Updating only `app` leaves the
infrastructure reverse proxy independent from application releases.

## Important operational rules

- Back up `/srv/income-book/clients` separately from the application code.
- Keep `.env`, client profiles, generated workbooks, certificates, and private
  keys outside Git.
- Bind port 8000 to the VM's private IP, not every interface, and restrict
  inbound access to the infrastructure reverse proxy or trusted internal
  network.
- If the optional Caddy profile is used, do not run `docker compose down -v`.
  The `-v` option deletes Caddy's internal certificate authority.
- Keep SSH limited to administrators and deployment accounts.
- HTTPS encrypts traffic but does not authenticate users. Application login and
  authorization are a separate feature.

## Diagnostics

```bash
docker compose ps
docker compose logs --tail 100 app
curl --fail http://10.0.0.10:8000/health
```

For the optional Caddy profile, also use:

```bash
docker compose logs --tail 100 caddy
curl --insecure --fail https://10.0.0.10/health
```

The application service should report `healthy`. VM snapshots provide the
infrastructure rollback point; Git provides the application-code history.
