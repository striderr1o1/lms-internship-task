# Northstar LMS API

FastAPI backend for a three-role learning system: student, teacher, and admin. The browser talks only to this API. The API owns passwords and sessions. Postgres is local, and Mux is used for lesson video uploads.

## What it does

- **Students** browse active courses, enroll, and open a course they have joined. A lesson includes its notes and a Mux playback id once the video is ready.
- **Teachers** create and rename courses, mark a course active or inactive, and add lessons with Markdown notes and an optional video. Lesson numbers stay contiguous inside a course.
- **Admins** see counts of students, teachers, and courses, plus each teacher's courses and the students enrolled in them. They also approve later admin signups.

Each account has one role. Sign-in must use the same role the account was created with.

## Stack

- Python 3.11+
- FastAPI and Uvicorn
- Local Postgres 17, accessed with a psycopg pool
- Mux direct uploads and webhooks

Schema for this database is [`postgres/migrations/001_init.sql`](postgres/migrations/001_init.sql). On a new data volume, Compose applies that file when Postgres starts. [`supabase/migrations`](supabase/migrations) is the old Supabase history and is not what you apply for this local database.

## Setup

1. Copy the env file and fill it in:

```bash
cp backend/.env.example backend/.env
```

2. Fill in `.env`:

| Variable | Purpose |
| --- | --- |
| `POSTGRES_USER` | Database user. The running database was created as `lms`. |
| `POSTGRES_PASSWORD` | Database password. |
| `POSTGRES_DB` | Database name. |
| `DATABASE_URL` | Host URL for tools on your machine, such as `psql`. The example uses `127.0.0.1:5433` with the user and password above. Compose overrides this for the API container so it connects to the `postgres` service. |
| `JWT_SECRET` | Signs access tokens. At least 32 characters. |
| `ACCESS_TOKEN_TTL_SECONDS` | Access token lifetime. Default `3600`. |
| `REFRESH_TOKEN_TTL_SECONDS` | Refresh token lifetime. Default `1209600` (14 days). |
| `FRONTEND_ORIGIN` | Browser origin allowed by CORS. Default `http://localhost:5173`. |
| `MUX_TOKEN_ID` | Mux API access token id |
| `MUX_TOKEN_SECRET` | Mux API access token secret |
| `MUX_WEBHOOK_SECRET` | Verifies `POST /api/webhooks/mux`. Optional until that route is used |

Do not commit `.env`.

3. From the repo root, build and start Postgres and the API:

```bash
docker compose up -d --build
```

Postgres 17 is published on `127.0.0.1:5433`. A `.env` file in the repo root is a symlink to `backend/.env`, which is where Compose reads `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`. The API is published on `127.0.0.1:8000` and connects to the `postgres` service with those same values.

- Health: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Auth

Passwords are hashed with Argon2id in the API. Signup writes `profiles` plus `students`, `teachers`, or `admins` in one transaction.

The first admin is approved. Later admins stay pending. The account is saved, and signup returns 403 with no tokens until an approved admin calls `POST /api/admins/{admin_id}/approve`.

Sign-in checks the password, then that the account role matches the portal. A wrong portal is 403. A pending admin is 403 with no tokens.

Access tokens are HS256 JWTs signed with `JWT_SECRET`. Lifetime is `ACCESS_TOKEN_TTL_SECONDS`. Claims are `sub`, `email`, `iat`, and `exp`. The API loads the role from `profiles` on each request. The token is not the source of the role. Send `Authorization: Bearer <access_token>`.

`POST /api/auth/refresh` takes `{ "refresh_token": "..." }`. The raw token is returned to the client. Only its SHA-256 hash is stored. Refresh rotates the token. Reuse of a revoked token revokes that profile's other refresh tokens.

There is no logout or password-reset route. The SPA still clears `sessionStorage` locally.

## Routes

All paths are under `/api`.

**Auth**

- `POST /auth/signup` with `{ username, email, password, role }`
- `POST /auth/signin` with `{ email, password, role }`
- `POST /auth/refresh`
- `GET /auth/me`

`username` is 3–32 characters: lowercase letters, digits, and underscores. `role` is `student`, `teacher`, or `admin`.

**Student**

- `GET /student/courses` lists active courses
- `GET /student/courses/{course_id}` returns the course and its lessons after enrollment
- `POST /student/courses/{course_id}/enroll`
- `GET /student/enrollments`

**Teacher**

- `GET /teacher/courses`
- `POST /teacher/courses` with `{ name }`
- `GET /teacher/courses/{course_id}`
- `PATCH /teacher/courses/{course_id}` with `{ name?, status? }`
- `DELETE /teacher/courses/{course_id}`
- `POST /teacher/courses/{course_id}/lessons` with `{ title, body, mux_asset_id? }`. A lesson video is either a Mux upload or a YouTube id.
- `PATCH /teacher/lessons/{lesson_id}`
- `DELETE /teacher/lessons/{lesson_id}` renumbers the remaining lessons
- `POST /teacher/videos/uploads` returns an upload URL for a video file
- `GET /teacher/videos/{video_id}` returns `waiting`, `asset_created`, `ready`, or `errored`

**Admin**

- `GET /admin/overview`
- `GET /admin/admins`
- `POST /admin/admins/{admin_id}/approve`

**Mux**

- `POST /webhooks/mux` accepts a Mux webhook signed with `MUX_WEBHOOK_SECRET`

A student sees `playback_id` only after the linked Mux asset is `ready`.
