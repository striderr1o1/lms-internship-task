# Northstar LMS API

FastAPI backend for a three-role learning system: student, teacher, and admin. The browser talks only to this API. The API owns Supabase Auth and Postgres, and it uses Mux for lesson video uploads.

## What it does

- **Students** browse active courses, enroll, and open a course they have joined. A lesson includes its notes and a Mux playback id once the video is ready.
- **Teachers** create and rename courses, mark a course active or inactive, and add lessons with Markdown notes and an optional video. Lesson numbers stay contiguous inside a course.
- **Admins** see counts of students, teachers, and courses, plus each teacher's courses and the students enrolled in them. They also approve later admin signups.

Each account has one role. Sign-in must use the same role the account was created with.

## Stack

- Python 3.11+
- FastAPI and Uvicorn
- Supabase Auth and Postgres, accessed with the Supabase Python client
- Mux direct uploads and webhooks

Schema lives in [`supabase/migrations`](supabase/migrations). Apply those files in filename order to the Supabase project before starting the API. `anon` and `authenticated` have no table access. The API uses the service role and checks the caller's role itself.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SECRET_KEY` | Service role key. Stays on the server. |
| `SUPABASE_PUBLISHABLE_KEY` | Used for password sign-in and token refresh |
| `FRONTEND_ORIGIN` | Browser origin allowed by CORS. Default `http://localhost:5173` |
| `MUX_TOKEN_ID` | Mux API access token id |
| `MUX_TOKEN_SECRET` | Mux API access token secret |
| `MUX_WEBHOOK_SECRET` | Verifies `POST /api/webhooks/mux`. Optional until that route is used |

Do not commit `.env`.

## Run

From `backend`, with the virtualenv active:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Health: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)
- Interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Auth

`POST /api/auth/signup` creates the Supabase user with `email_confirm` already set. The role and username go in `app_metadata`. A trigger on `auth.users` writes `profiles` and the matching `students`, `teachers`, or `admins` row.

The first admin is approved automatically. Every later admin stays `pending` and receives no session until an approved admin calls `POST /api/admins/{admin_id}/approve`.

`POST /api/auth/signin` checks the password, then checks that the account's role matches the portal that was selected. Access tokens are Supabase ES256 JWTs. The API verifies them against the project JWKS and loads the profile from Postgres on each request. Send `Authorization: Bearer <access_token>`. `POST /api/auth/refresh` takes `{ "refresh_token": "..." }`.

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
- `POST /teacher/courses/{course_id}/lessons` with `{ title, body, mux_asset_id? }`
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
