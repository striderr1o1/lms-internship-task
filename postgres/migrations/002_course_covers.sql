-- Course covers. Nullable columns only, so existing rows stay as they are.
-- Safe to run once on a database that already has 001 applied.

alter table public.courses add column if not exists cover_image_url text;
alter table public.courses add column if not exists cover_source text;
alter table public.courses add column if not exists cover_alt text;
alter table public.courses add column if not exists cover_color text;
alter table public.courses add column if not exists cover_blur_hash text;
alter table public.courses add column if not exists cover_unsplash_id text;
alter table public.courses add column if not exists cover_credit_name text;
alter table public.courses add column if not exists cover_credit_url text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'courses_cover_source_check'
      and conrelid = 'public.courses'::regclass
  ) then
    alter table public.courses
      add constraint courses_cover_source_check
      check (cover_source is null or cover_source in ('unsplash', 'url', 'upload', 'generated'));
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'courses_cover_color_check'
      and conrelid = 'public.courses'::regclass
  ) then
    alter table public.courses
      add constraint courses_cover_color_check
      check (cover_color is null or cover_color ~ '^#[0-9A-Fa-f]{6}$');
  end if;
end $$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'courses_cover_image_url_len'
      and conrelid = 'public.courses'::regclass
  ) then
    alter table public.courses
      add constraint courses_cover_image_url_len
      check (cover_image_url is null or char_length(cover_image_url) <= 2048);
  end if;
end $$;
