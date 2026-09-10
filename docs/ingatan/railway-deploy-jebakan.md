---
name: railway-deploy-jebakan
description: Three Railway deploy traps that cost 3 failed deploys — verify in the Docker image, not the laptop venv
metadata:
  type: feedback
---

Deploying the timbangan service on 2026-08-30 failed **three times**, each a
different cause, all the same root mistake: **testing in the laptop venv and
assuming the container behaves the same.** 224 tests passed while all three
faults were present.

1. **Dockerfile copies only what it names.** It copies `app`, `migrations`,
   `alembic.ini`, and ONE entrypoint — not the `docker/` directory. A second
   script added there simply does not exist in the image.
2. **Railway replaces `CMD`, not `ENTRYPOINT`.** A Custom Start Command is
   passed as arguments to the existing ENTRYPOINT, and is run as an argv list,
   **not through a shell** — so `$PORT` is never expanded and uvicorn rejects
   it. Wrap it: `sh -c "uvicorn ... --port ${PORT:-8000}"`. The symptom is
   misleading: Build and Deploy go green, then Healthcheck fails without ever
   mentioning the port.
3. **Deps present locally as transitive packages are missing in the image.**
   `jinja2`, `python-multipart`, `aiofiles` were never in requirements.txt.

4. **A repo that is not itself `railway link`-ed uploads its PARENT.** After the
   2026-09-02 split into a workspace of sibling repos, only
   `~/Developer/Hadi Mulya Systems` (plus `kantor` and `produksi`) were linked —
   `timbangan` was not. `railway up` run from inside `timbangan/` therefore
   uploaded the whole workspace, and Railpack failed with "could not determine
   how to build the app" listing the five sibling directories. Fix:
   `railway link --project <id> --environment production --service <name>` from
   inside the repo. Linked paths live in `~/.railway/config.json`; check there
   first when a deploy uploads the wrong tree. The running service was never
   touched — the build failed before any swap.

**How to avoid repeating it:** before pushing a deploy change, build the image
and run it locally — `docker build -t cek . && docker run ... sh -c "uvicorn
..."` — then curl the health endpoint. That check catches all three in one go.
Scanning the module's imports (`ast`) against requirements.txt catches missing
deps before the container does.

**Why it matters here specifically:** all three Railway services build from one
repo with auto-deploy on `main`, so every push restarts the Telegram bots
(brief `409 Conflict`, self-healing). Three failed deploys = three needless bot
restarts. Consider per-service **Watch Paths** to stop unrelated pushes from
rebuilding everything. See [[railway-deploy]] and [[timbangan-module]].
