-- Applied once, by hand, to an empty database.

create table public.profiles (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  password_hash text not null,
  username text not null,
  role text not null,
  created_at timestamptz not null default now(),
  constraint profiles_email_key unique (email),
  constraint profiles_username_format check (username ~ '^[a-z0-9_]{3,32}$'),
  constraint profiles_role_check check (role in ('student', 'teacher', 'admin')),
  constraint profiles_email_lower_check check (email = lower(email))
);

create unique index profiles_username_key on public.profiles (username);

create table public.students (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null unique references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now()
);

create table public.teachers (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null unique references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now()
);

create table public.admins (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null unique references public.profiles (id) on delete cascade,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  constraint admins_status_check check (status in ('pending', 'approved'))
);

create index admins_pending_idx on public.admins (created_at) where status = 'pending';

create table public.courses (
  id uuid primary key default gen_random_uuid(),
  teacher_id uuid not null references public.teachers (id) on delete cascade,
  name text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  constraint courses_name_len check (char_length(name) between 1 and 120),
  constraint courses_status_check check (status in ('active', 'inactive'))
);

create index courses_teacher_id_idx on public.courses (teacher_id);
create index courses_active_idx on public.courses (created_at desc) where status = 'active';

create table public.mux_assets (
  id uuid primary key default gen_random_uuid(),
  teacher_id uuid not null references public.teachers (id) on delete cascade,
  upload_id text not null unique,
  mux_asset_id text unique,
  playback_id text,
  status text not null default 'waiting',
  created_at timestamptz not null default now(),
  constraint mux_assets_status_check check (status in ('waiting', 'asset_created', 'ready', 'errored'))
);

create index mux_assets_teacher_id_idx on public.mux_assets (teacher_id);

create table public.lessons (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses (id) on delete cascade,
  lesson_number integer not null,
  title text not null,
  body text not null default '',
  mux_asset_id uuid references public.mux_assets (id) on delete set null,
  youtube_video_id text,
  created_at timestamptz not null default now(),
  constraint lessons_number_positive check (lesson_number > 0),
  constraint lessons_title_len check (char_length(title) between 1 and 160),
  constraint lessons_youtube_video_id_check check (
    youtube_video_id is null or youtube_video_id ~ '^[A-Za-z0-9_-]{11}$'
  ),
  constraint lessons_one_video_check check (mux_asset_id is null or youtube_video_id is null),
  constraint lessons_course_number_key unique (course_id, lesson_number) deferrable initially deferred
);

create index lessons_course_id_idx on public.lessons (course_id);
create index lessons_mux_asset_id_idx on public.lessons (mux_asset_id);

create table public.enrollments (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references public.students (id) on delete cascade,
  course_id uuid not null references public.courses (id) on delete cascade,
  enrolled_at timestamptz not null default now(),
  constraint enrollments_student_course_key unique (student_id, course_id)
);

create index enrollments_student_id_idx on public.enrollments (student_id);
create index enrollments_course_id_idx on public.enrollments (course_id);

create table public.refresh_tokens (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.profiles (id) on delete cascade,
  token_hash text not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  constraint refresh_tokens_token_hash_hex_check check (token_hash ~ '^[0-9a-f]{64}$')
);

create unique index refresh_tokens_token_hash_key on public.refresh_tokens (token_hash);
create index refresh_tokens_profile_id_idx on public.refresh_tokens (profile_id);

create function public.create_lesson(
  p_course_id uuid,
  p_teacher_id uuid,
  p_title text,
  p_body text,
  p_mux_asset_id uuid,
  p_youtube_video_id text
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_owner uuid;
  v_asset_owner uuid;
  v_number integer;
  v_id uuid;
begin
  select c.teacher_id
    into v_owner
  from public.courses as c
  where c.id = p_course_id
  for update;

  if v_owner is null or v_owner is distinct from p_teacher_id then
    raise exception 'not found'
      using errcode = 'P0002';
  end if;

  if p_mux_asset_id is not null then
    select m.teacher_id
      into v_asset_owner
    from public.mux_assets as m
    where m.id = p_mux_asset_id;

    if v_asset_owner is null or v_asset_owner is distinct from p_teacher_id then
      raise exception 'not found'
        using errcode = 'P0002';
    end if;
  end if;

  select coalesce(max(l.lesson_number), 0) + 1
    into v_number
  from public.lessons as l
  where l.course_id = p_course_id;

  insert into public.lessons (
    course_id,
    lesson_number,
    title,
    body,
    mux_asset_id,
    youtube_video_id
  )
  values (
    p_course_id,
    v_number,
    p_title,
    coalesce(p_body, ''),
    p_mux_asset_id,
    p_youtube_video_id
  )
  returning id into v_id;

  return v_id;
end;
$$;

create function public.delete_lesson(
  p_lesson_id uuid,
  p_teacher_id uuid
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_course_id uuid;
begin
  select c.id
    into v_course_id
  from public.lessons as l
  join public.courses as c on c.id = l.course_id
  where l.id = p_lesson_id
    and c.teacher_id = p_teacher_id
  for update of c;

  if v_course_id is null then
    raise exception 'not found'
      using errcode = 'P0002';
  end if;

  delete from public.lessons
  where id = p_lesson_id;

  with ordered as (
    select id, row_number() over (order by lesson_number) as new_number
    from public.lessons
    where course_id = v_course_id
  )
  update public.lessons as l
  set lesson_number = ordered.new_number
  from ordered
  where l.id = ordered.id
    and l.lesson_number is distinct from ordered.new_number;
end;
$$;

revoke all on function public.create_lesson(uuid, uuid, text, text, uuid, text) from public;
revoke all on function public.delete_lesson(uuid, uuid) from public;
