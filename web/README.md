# Kept web (Track D)

Next.js 16 (App Router) + Tailwind 4. Pages: case lookup, the NBA card with review and release
(`/cases/[caseId]`), Collections Ask (`/ask`), and the steward match queue (`/steward`).

```bash
make web-setup                 # pnpm install
make serve-demo                # API on :8000 with three demo cases (CS-DEMO-CALL, -HARDSHIP, -STOP)
make web                       # http://localhost:3000 (use localhost, not 127.0.0.1, in dev)
```

The browser calls `/api/*`; Next forwards it to the API at `KEPT_API_URL` (default
`http://127.0.0.1:8000`). If port 8000 is taken: `uv run kept serve --demo --port 8010` and
`KEPT_API_URL=http://127.0.0.1:8010 pnpm dev`.

Opening it from another PC: the dev server only serves its scripts to `localhost`, so list this
machine's LAN IPs (`ip -4 addr`): `KEPT_DEV_ORIGINS=10.42.0.1,10.1.37.147 pnpm dev`, then open
`http://<ip>:3000` on the other PC. Without it the page loads but stays on the loading skeleton.

API types are generated from the FastAPI schema, so they follow `src/kept/contracts`:
`pnpm api:types` after any contract change. Identity (user and role) is picked in the header and
kept in localStorage: a demo stand-in for sign-in.
