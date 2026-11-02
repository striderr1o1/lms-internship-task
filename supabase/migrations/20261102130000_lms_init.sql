create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  username text not null,
  role text not null,
  created_at timestamptz not null default now(),
  constraint profiles_username_format check (username ~ '^[a-z0-9_]{3,32}$'),
  constraint profiles_role_check check (role in ('student', 'teacher', 'admin'))
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
  created_at timestamptz not null default now(),
  constraint lessons_number_positive check (lesson_number > 0),
  constraint lessons_title_len check (char_length(title) between 1 and 160),
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

revoke all on table public.profiles from public, anon, authenticated;
revoke all on table public.students from public, anon, authenticated;
revoke all on table public.teachers from public, anon, authenticated;
revoke all on table public.admins from public, anon, authenticated;
revoke all on table public.courses from public, anon, authenticated;
revoke all on table public.mux_assets from public, anon, authenticated;
revoke all on table public.lessons from public, anon, authenticated;
revoke all on table public.enrollments from public, anon, authenticated;

grant select, insert, update, delete on table public.profiles to service_role;
grant select, insert, update, delete on table public.students to service_role;
grant select, insert, update, delete on table public.teachers to service_role;
grant select, insert, update, delete on table public.admins to service_role;
grant select, insert, update, delete on table public.courses to service_role;
grant select, insert, update, delete on table public.mux_assets to service_role;
grant select, insert, update, delete on table public.lessons to service_role;
grant select, insert, update, delete on table public.enrollments to service_role;

alter table public.profiles enable row level security;
alter table public.profiles force row level security;
alter table public.students enable row level security;
alter table public.students force row level security;
alter table public.teachers enable row level security;
alter table public.teachers force row level security;
alter table public.admins enable row level security;
alter table public.admins force row level security;
alter table public.courses enable row level security;
alter table public.courses force row level security;
alter table public.mux_assets enable row level security;
alter table public.mux_assets force row level security;
alter table public.lessons enable row level security;
alter table public.lessons force row level security;
alter table public.enrollments enable row level security;
alter table public.enrollments force row level security;

create or replace function private.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  new_role text;
  new_username text;
  admin_status text;
begin
  new_role := coalesce(new.raw_app_meta_data->>'role', '');
  new_username := coalesce(new.raw_app_meta_data->>'username', '');

  if new_role not in ('student', 'teacher', 'admin') then
    raise exception 'invalid role';
  end if;
  if new_username !~ '^[a-z0-9_]{3,32}$' then
    raise exception 'invalid username';
  end if;

  insert into public.profiles (id, username, role)
  values (new.id, new_username, new_role);

  if new_role = 'student' then
    insert into public.students (profile_id) values (new.id);
  elsif new_role = 'teacher' then
    insert into public.teachers (profile_id) values (new.id);
  else
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('lms_first_admin')::bigint);
    if exists (select 1 from public.admins where status = 'approved') then
      admin_status := 'pending';
    else
      admin_status := 'approved';
    end if;
    insert into public.admins (profile_id, status) values (new.id, admin_status);
  end if;

  return new;
end;
$$;

revoke all on function private.handle_new_user() from public, anon, authenticated;
grant usage on schema private to supabase_auth_admin;
grant execute on function private.handle_new_user() to supabase_auth_admin;

create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function private.handle_new_user();

create or replace function public.create_lesson(
  p_course_id uuid,
  p_teacher_id uuid,
  p_title text,
  p_body text,
  p_mux_asset_id uuid
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

  insert into public.lessons (course_id, lesson_number, title, body, mux_asset_id)
  values (p_course_id, v_number, p_title, coalesce(p_body, ''), p_mux_asset_id)
  returning id into v_id;

  return v_id;
end;
$$;

create or replace function public.delete_lesson(
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

revoke all on function public.create_lesson(uuid, uuid, text, text, uuid) from public, anon, authenticated;
revoke all on function public.delete_lesson(uuid, uuid) from public, anon, authenticated;
grant execute on function public.create_lesson(uuid, uuid, text, text, uuid) to service_role;
grant execute on function public.delete_lesson(uuid, uuid) to service_role;

notify pgrst, 'reload schema';
