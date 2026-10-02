# Docker and local operations

Each service has a focused Dockerfile. Engine and simulator use multi-stage Debian builds,
leaving compilers out of runtime images. API/risk use Python 3.12 slim as the unprivileged
`nobody` user. Frontend compiles under Node 22 and is served from nginx. `.dockerignore`
files keep modules, tests, caches, and local builds out of contexts.

`docker-compose.yml` supplies one network, the persistent `postgres_data` volume, health
checks, dependency conditions, environment configuration, exposed ports, and restart
policies. Core startup order is database/engine → risk → API → frontend. The simulator and
Prometheus are opt-in profiles.

```bash
make run
docker compose ps
docker compose logs -f api matching-engine
make stop
```

`make demo` starts the same stack with the opt-in continuous simulator profile. `make
demo-reset` explicitly removes the local database volume before a clean demonstration;
it is destructive and intended only for disposable local data. `make reset` also removes
the APEX database volume. Migrations run automatically only when PostgreSQL initializes an empty volume; a
production deployment should run them as an explicit release job.

Configuration comes from Compose defaults or `.env` copied from `.env.example`. The
checked-in password is a local-only default. Never reuse it outside the private Compose
network. Image tags are pinned for PostgreSQL, nginx, and Prometheus; application Python
dependencies are pinned, while frontend lockfile records the exact npm graph.
