-- Auth inserts the user first, then writes app_metadata. Provision on that update.

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

  if new_role not in ('student', 'teacher', 'admin')
     or new_username !~ '^[a-z0-9_]{3,32}$' then
    return new;
  end if;

  if exists (select 1 from public.profiles where id = new.id) then
    return new;
  end if;

  insert into public.profiles (id, username, role)
  values (new.id, new_username, new_role);

  if new_role = 'student' then
    insert into public.students (profile_id) values (new.id);
  elsif new_role = 'teacher' then
    insert into public.teachers (profile_id) values (new.id);
  else
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('lms_first_admin'));
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

drop trigger if exists on_auth_user_app_meta on auth.users;
create trigger on_auth_user_app_meta
  after update of raw_app_meta_data on auth.users
  for each row
  execute function private.handle_new_user();

drop table if exists private.signup_debug;
