# RLS Model v1

Default deny em todas as tabelas de produto.

## Helpers (SECURITY DEFINER, search_path=public)

- `is_platform_admin()`
- `has_school_role(school_id, roles[])`
- `my_school_ids()`
- `my_teacher_class_group_ids()`

## Roles

| Role | Escopo |
|------|--------|
| platform_admin | `profiles.is_platform_admin` |
| gestor | membership na escola — cadastro |
| professor | turmas em `teacher_assignments` |
| monitor | leitura operacional da escola |
| device | **não** usa Auth; Edge Function + `device_credentials.token_hash` |

## Browser

anon/publishable key + JWT. **Nunca** service_role.

## Correção aplicada

`REVOKE EXECUTE ON public.rls_auto_enable() FROM PUBLIC, anon, authenticated`  
(event trigger `ensure_rls` preservado).
