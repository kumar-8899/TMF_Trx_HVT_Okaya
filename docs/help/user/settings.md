# Settings

Station administration (super_admin).

## Data management
Select what to permanently delete, then **Reset selected**:
- Runs & history, Reports, Logs, Recipes, Users (except super_admin).

This is destructive and cannot be undone. The super_admin account is always preserved.

## Report database
Reports are stored on a **professional DB server (MySQL or SQL Server)**, not the local
station. Pick the **provider**, enter the connection details (host, port, database, user,
password; SQL Server also needs the ODBC driver name), press **Test connection** (this
creates the report tables), then **Save**.

- Leave **Password** blank to keep the stored one.
- Reports are spooled locally first and forwarded to the DB, so a database outage never
  blocks testing — queued reports drain automatically when the DB is back.
- Until a database is configured, new reports queue locally and the Reports / Analytics
  pages show a "not configured" note.
