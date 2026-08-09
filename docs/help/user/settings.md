# Settings

Station administration (super_admin).

## Station configuration
Set how many **test sockets** this PC runs and which **controller** serves them.

- **Test sockets** — the number of independent stations (`st1`, `st2`, …). One
  socket behaves as a single-station system (no station picker anywhere). The
  maximum is set by your licence; the field shows the cap.
- **Controller** — **LabVIEW** (the engine runs separately, as before) or
  **Python** (the app starts and stops the bundled Python controller for you).
  Simulation vs hardware is **not** set here — it is a per-instrument choice, the
  **Simulated** toggle on the **Instruments** page.

These are start-up settings. Press **Save** to write them, then **Relaunch to
apply** to restart the station with the new configuration. The banner shows
"restart required" until you relaunch.

## Exiting the station
The **power icon** in the top bar (super_admin) exits the station **safely**: it
drives every instrument to its safe state, stops the controller, and closes the
app without restarting it. Relaunch it from the desktop shortcut (or `dev.ps1`) to
bring it back. Use this rather than closing the window, so nothing is left
energised.

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
