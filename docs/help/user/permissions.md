# Permissions

A role × permission matrix (super_admin only, **AUTH.MANAGE_ROLES**).

![Permissions — role to permission matrix](asset:permissions)

- Toggle each permission per role, grouped by domain.
- **super_admin** is read-only — it always holds every permission.
- **Changes apply at each user's next login** (permissions are resolved at sign-in; live sessions are unaffected).

Use this to widen or restrict what operators / engineers / maintenance / admin can do.
