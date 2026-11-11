# PostgreSQL migration (10 Nov 2026)

`compose.yaml` runs Postgres 17 and the API. Live Supabase rows were not imported.

`postgres/migrations/001_init.sql` is the schema. `profiles` holds email and `password_hash`. `refresh_tokens` stores SHA-256 hashes. No RLS, no `auth.users`, no GoTrue.

The API hashes passwords with Argon2id, signs access tokens with HS256, rotates refresh tokens, and uses a psycopg pool.

Still out of scope: a VPS, Caddy, importing the old Supabase data, frontend edits, and logout.
