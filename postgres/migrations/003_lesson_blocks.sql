-- Lesson blocks. Safe to re-run.
-- Backfills from the old lesson columns when they still exist, then drops them.
-- No-op on a database that is already in the final shape.

create table if not exists public.lesson_blocks (
  id uuid primary key default gen_random_uuid(),
  lesson_id uuid not null,
  position integer not null,
  kind text not null,
  body text not null default '',
  mux_asset_id uuid,
  youtube_video_id text,
  constraint lesson_blocks_lesson_id_fkey
    foreign key (lesson_id) references public.lessons (id) on delete cascade,
  constraint lesson_blocks_mux_asset_id_fkey
    foreign key (mux_asset_id) references public.mux_assets (id) on delete set null,
  constraint lesson_blocks_position_positive check (position > 0),
  constraint lesson_blocks_kind_check check (kind in ('text', 'video')),
  constraint lesson_blocks_youtube_video_id_check check (
    youtube_video_id is null or youtube_video_id ~ '^[A-Za-z0-9_-]{11}$'
  ),
  constraint lesson_blocks_shape_check check (
    (
      kind = 'text'
      and mux_asset_id is null
      and youtube_video_id is null
    )
    or (
      kind = 'video'
      and (
        (mux_asset_id is not null and youtube_video_id is null)
        or (mux_asset_id is null and youtube_video_id is not null)
      )
    )
  ),
  constraint lesson_blocks_lesson_position_key unique (lesson_id, position)
);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_lesson_id_fkey'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_lesson_id_fkey
      foreign key (lesson_id) references public.lessons (id) on delete cascade;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_mux_asset_id_fkey'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_mux_asset_id_fkey
      foreign key (mux_asset_id) references public.mux_assets (id) on delete set null;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_position_positive'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_position_positive
      check (position > 0);
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_kind_check'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_kind_check
      check (kind in ('text', 'video'));
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_youtube_video_id_check'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_youtube_video_id_check
      check (youtube_video_id is null or youtube_video_id ~ '^[A-Za-z0-9_-]{11}$');
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_shape_check'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_shape_check
      check (
        (
          kind = 'text'
          and mux_asset_id is null
          and youtube_video_id is null
        )
        or (
          kind = 'video'
          and (
            (mux_asset_id is not null and youtube_video_id is null)
            or (mux_asset_id is null and youtube_video_id is not null)
          )
        )
      );
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'lesson_blocks_lesson_position_key'
      and conrelid = 'public.lesson_blocks'::regclass
  ) then
    alter table public.lesson_blocks
      add constraint lesson_blocks_lesson_position_key
      unique (lesson_id, position);
  end if;
end $$;

create index if not exists lesson_blocks_lesson_id_idx
  on public.lesson_blocks (lesson_id);

create index if not exists lesson_blocks_mux_asset_id_idx
  on public.lesson_blocks (mux_asset_id);

do $$
begin
  if exists (
    select 1
    from pg_attribute
    where attrelid = 'public.lessons'::regclass
      and attname = 'body'
      and not attisdropped
  ) then
    execute $backfill$
      with candidates as (
        select
          l.id,
          l.body,
          l.mux_asset_id,
          l.youtube_video_id
        from public.lessons as l
        where not exists (
          select 1
          from public.lesson_blocks as b
          where b.lesson_id = l.id
        )
      )
      insert into public.lesson_blocks (
        lesson_id,
        position,
        kind,
        body,
        mux_asset_id,
        youtube_video_id
      )
      select
        c.id,
        1,
        'video',
        '',
        c.mux_asset_id,
        c.youtube_video_id
      from candidates as c
      where c.mux_asset_id is not null
         or c.youtube_video_id is not null
      union all
      select
        c.id,
        case
          when c.mux_asset_id is not null or c.youtube_video_id is not null then 2
          else 1
        end,
        'text',
        c.body,
        null::uuid,
        null::text
      from candidates as c
      where btrim(c.body) <> ''
    $backfill$;
  end if;
end $$;

drop function if exists public.create_lesson(uuid, uuid, text, text, uuid, text);

alter table public.lessons drop constraint if exists lessons_one_video_check;
alter table public.lessons drop constraint if exists lessons_youtube_video_id_check;

drop index if exists public.lessons_mux_asset_id_idx;

alter table public.lessons drop column if exists body;
alter table public.lessons drop column if exists mux_asset_id;
alter table public.lessons drop column if exists youtube_video_id;

create or replace function public.create_lesson(
  p_course_id uuid,
  p_teacher_id uuid,
  p_title text
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_owner uuid;
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

  select coalesce(max(l.lesson_number), 0) + 1
    into v_number
  from public.lessons as l
  where l.course_id = p_course_id;

  insert into public.lessons (
    course_id,
    lesson_number,
    title
  )
  values (
    p_course_id,
    v_number,
    p_title
  )
  returning id into v_id;

  return v_id;
end;
$$;

revoke all on function public.create_lesson(uuid, uuid, text) from public;
