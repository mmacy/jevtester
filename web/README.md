# jevtester web UI

The web UI for jevtester, built with React, TypeScript, Vite, and Tailwind CSS. [`docs/ui-plan.md`](../docs/ui-plan.md) describes the views.

## Develop

```sh
npm install
npm run dev            # proxies /api to the backend at 127.0.0.1:8640
npm run dev:fixtures   # answers /api from tests/fixtures/api/, no backend needed
```

Both serve at <http://127.0.0.1:5173>.

In fixture mode, a fixture's file name is the method and the path after `/api`, joined with underscores. A `{name}` part matches any one path segment, and a `.sse` or `.txt` file replays as server-sent events. For example, `get_runs_{id}_events.sse` answers `GET /api/runs/0142/events`. A variant adds a dot and a name after the route part, like `post_decide.partial.json` or `post_decide.422.json`. A request gets a variant only when its `X-Fixture` header names it, and a numeric variant is served with that HTTP status. Set `JEVTESTER_FIXTURES` to use another directory.

## API types

`src/api/generated.ts` is generated from `docs/openapi.json`. Don't edit it. Regenerate it after the contract changes:

```sh
npm run gen:api
```

## Build

```sh
npm run build
```

The build writes to `src/jevtester/static/`, which `jevtester serve` serves and git ignores.

## Gates

```sh
npx prettier --check .
npx eslint .
npx tsc -b
npx vitest run
npx playwright test
```

Playwright runs against fixture mode on port 5174.

To check the built UI as `jevtester serve` ships it, against the real API on port 8645, run `npm run e2e:serve`. It needs uv. It asks no target anything, though the server still creates or updates `.jevtester/runs.sqlite` as it starts.
