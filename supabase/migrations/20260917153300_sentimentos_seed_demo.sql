-- Seed mínimo Dulino / Escola Demo (IDs estáveis para CLOUD_* env no edge)
insert into public.organizations (id, name, slug)
values ('11111111-1111-1111-1111-111111111111', 'Dulino', 'dulino')
on conflict (slug) do update set name = excluded.name;

insert into public.schools (id, organization_id, name)
values (
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111',
  'Escola Demo Sentimentos'
)
on conflict (id) do update set name = excluded.name;
