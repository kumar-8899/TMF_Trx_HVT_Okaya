# Users

Manage accounts (needs **AUTH.MANAGE_USERS**).

- **New user** — username + role; a temporary password is shown once (the user must change it at first login).
- **Role dropdown** per user; **state** chips (active / locked / inactive).
- **Lock / unlock / activate / deactivate / reset password** per row.
- **super_admin** is a protected singleton — hidden from non-super_admins and cannot be deleted or demoted.

To edit what each role can do, open **Permissions** (super_admin only).
