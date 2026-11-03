alter table public.lessons
  add column youtube_video_id text;

alter table public.lessons
  add constraint lessons_youtube_video_id_check
  check (youtube_video_id is null or youtube_video_id ~ '^[A-Za-z0-9_-]{11}$');

alter table public.lessons
  add constraint lessons_one_video_check
  check (mux_asset_id is null or youtube_video_id is null);

drop function public.create_lesson(uuid, uuid, text, text, uuid);

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

revoke all on function public.create_lesson(uuid, uuid, text, text, uuid, text) from public, anon, authenticated;
grant execute on function public.create_lesson(uuid, uuid, text, text, uuid, text) to service_role;

notify pgrst, 'reload schema';
