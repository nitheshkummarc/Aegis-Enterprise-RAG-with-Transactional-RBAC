# Aegis Frontend

Next.js 15 (App Router) chat UI for Aegis — a permission-aware RAG system.
See the [root README](../README.md) for the full project overview and the
[architecture doc](../backend/docs/ARCHITECTURE.md) for how RBAC is enforced.

## How auth actually works

Login is handled by NextAuth v5's credentials provider ([`src/auth.ts`](src/auth.ts)):
the login form posts email/password to the *backend's* `/auth/login`
endpoint, which returns a JWT; NextAuth stores that JWT in the session and
[`src/lib/api.ts`](src/lib/api.ts)'s `fetchWithAuth` attaches it as a
`Authorization: Bearer` header on every backend call.

`src/utils/supabase/{client,server}.ts` are **not currently used** — nothing
in the app calls `createClient()` from either file. Auth doesn't go through
Supabase Auth at all; only the backend talks to Supabase, and only for file
storage.

## Getting Started

```bash
npm install
cp .env.example .env.local   # fill in NEXT_PUBLIC_BACKEND_URL and NEXTAUTH_SECRET
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Login with one of the
backend's seeded test users (see the root README).

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | Yes | Backend API base URL. Read by both `auth.ts` (server-side login) and `lib/api.ts` (also runs client-side, hence `NEXT_PUBLIC_`). |
| `NEXTAUTH_SECRET` | Yes for `npm run start` | Auth.js tolerates a missing secret in `npm run dev` (console warning only) but throws in production. |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | No | Currently unused — see above. Only needed if you wire up direct Supabase usage. |

## Scripts

```bash
npm run dev     # start the dev server
npm run build   # production build (also type-checks)
npm run start   # run a production build
npm run lint    # eslint
npm test        # jest — component tests (src under tests/)
```

## Structure

- `src/app/` — App Router pages: `/login`, `/chat` (the SSE chat UI), and the NextAuth route handler under `api/auth/`.
- `src/auth.ts` — NextAuth v5 config (credentials provider → backend `/auth/login`).
- `src/lib/api.ts` — `fetchWithAuth`, the only place backend calls are made from.
- `src/components/SourcesDropdown.tsx` — renders the permitted sources returned by a query, or the "no permitted sources" refusal state. Its "Admin Upload" badge is a role-conditional visual cue, not a wired-up upload flow — there is no upload UI yet; document ingestion currently happens via the backend's `scripts/generate_synthetic_corpus.py` or direct API calls to `/documents/upload-url` + `/documents/confirm-upload`.
