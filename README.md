# Northstar LMS API

FastAPI backend for a three-role learning system: student, teacher, and admin. The browser talks only to this API. The API owns passwords and sessions. Postgres is local, and Mux is used for lesson video uploads.

## What it does

- **Students** see only the active courses an admin assigned to them. A lesson is an ordered list of text and video blocks. A video plays from Mux once that asset is `ready`, or from YouTube.
- **Teachers** open the courses an admin assigned to them. They add lessons, and each lesson is 1 to 40 blocks of Markdown notes and videos. A video block is either a Mux upload or a YouTube URL. Lesson numbers stay contiguous inside a course. Teachers do not create or delete courses.
- **Admins** create courses, name them, assign a teacher and the students who can see them, and set a cover. They see counts of students, teachers, and courses, and they approve later admin signups.

Each account has one role. Sign-in must use the same role the account was created with.

## Stack

- Python 3.11+
- FastAPI and Uvicorn
- Local Postgres 17, accessed with a psycopg pool
- Mux direct uploads and webhooks

[`postgres/migrations/001_init.sql`](postgres/migrations/001_init.sql) is the schema for a new database, including course covers and `lesson_blocks`. Compose applies that file when Postgres starts on an empty data volume. [`002_course_covers.sql`](postgres/migrations/002_course_covers.sql) and [`003_lesson_blocks.sql`](postgres/migrations/003_lesson_blocks.sql) upgrade a database created from an older `001`. Both are safe to run again. [`supabase/migrations`](supabase/migrations) is the old Supabase history and is not what you apply for this local database.

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
| `UNSPLASH_ACCESS_KEY` | Unsplash access key for cover search. If it is empty, search returns 503 and the cover picker hides the Unsplash tab |

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

- `GET /student/courses` lists active courses assigned to the student
- `GET /student/courses/{course_id}` returns one assigned active course and its lessons
- `GET /student/enrollments` lists the same assigned active courses

Each lesson is `{ id, lesson_number, title, blocks }`. A text block is `{ id, position, kind: "text", body }`. A video block is `{ id, position, kind: "video", playback_id, youtube_video_id }`. `playback_id` is set only when the Mux asset is `ready`. Students do not receive `mux_asset_id`.

**Teacher**

- `GET /teacher/courses`
- `GET /teacher/courses/{course_id}`
- `POST /teacher/courses/{course_id}/lessons` with `{ title, blocks }`
- `PATCH /teacher/lessons/{lesson_id}` with at least one of `title` or `blocks`
- `DELETE /teacher/lessons/{lesson_id}` renumbers the remaining lessons
- `POST /teacher/videos/uploads` returns an upload URL for a video file
- `GET /teacher/videos/{video_id}` returns `waiting`, `asset_created`, `ready`, or `errored`

`blocks` has 1 to 40 items. A text block is `{ kind: "text", body }`. A video block sends exactly one of `{ kind: "video", mux_asset_id }` or `{ kind: "video", youtube_url }`. The lesson is rejected when every text block is blank and there is no video. Sending `blocks` replaces the whole list. A teacher video block in the response also includes `mux_asset_id`, `video_status`, and `video_source` (`mux` or `youtube`).

**Admin**

- `GET /admin/overview`
- `GET /admin/teachers`
- `GET /admin/students`
- `GET /admin/admins` lists pending admins by default. `?status=approved` lists approved admins
- `POST /admin/admins/{admin_id}/approve`
- `POST /admin/courses` with `{ teacher_id, name, student_ids, cover? }`
- `PATCH /admin/courses/{course_id}` with at least one of `name`, `status` (`active` or `inactive`), or `cover`
- `DELETE /admin/courses/{course_id}`
- `POST /admin/courses/{course_id}/students` with `{ student_id }`
- `DELETE /admin/courses/{course_id}/students/{student_id}`

`cover.source` is `unsplash`, `url`, or `generated`. A pasted cover stores the https URL. The API does not fetch it. Local hosts such as `localhost` and `127.0.0.1` are rejected.

**Public**

- `GET /public/stats` returns `{ courses, lessons, learners }`
- `GET /public/courses/featured` returns up to 6 active courses with a cover, lesson count, and teacher display name

**Images**

- `GET /images/unsplash/search?query=&page=` searches Unsplash for an admin. It returns 503 when `UNSPLASH_ACCESS_KEY` is missing or Unsplash is unavailable

**Mux**

- `POST /webhooks/mux` accepts a Mux webhook signed with `MUX_WEBHOOK_SECRET`
