# Settings

Station administration (super_admin).

![Settings — station administration](asset:settings)

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

## Remote debugging
A **flight recorder** that quietly records what the station does, so a fault — even
one overnight with nobody watching — can be diagnosed afterwards.

- **Enable the flight recorder** — turns it on. It runs as a separate helper (so it
  keeps recording even while the app itself restarts) and shows **running**/**stopped**
  plus how much it has recorded today.
- **Continuous recording to disk** — keeps a rolling log and a 30-second detailed
  snapshot around each failure.
- **Access from** — leave at **127.0.0.1** (this machine only) unless a developer needs
  to connect from their laptop; then enter this PC's network address and set an **access
  token** (required for anything but this machine).

These are start-up settings: press **Save**, then **Relaunch to apply**. When it is off,
nothing extra runs. A developer collects a recording with the `tmf-debug` tool.

## Exiting the station
Open the **user menu** (your avatar, top-right) and choose **Exit station**
(super_admin). It exits **safely**: drives every instrument to its safe state, stops
the controller, and closes the app without restarting it. Relaunch it from the
desktop shortcut (or `dev.ps1` / `python station.py`) to bring it back. Closing the
app window does the same safe shutdown — but use **Exit station** so nothing is left
energised if the window is only minimised.

## Application updates
Check for, download and install signed application updates. Nothing installs on its
own — **Check**, then **Download**, then **Install**, then **Relaunch**. The launcher
swaps the new version in on the next start and automatically rolls back to the last
known good build if the new one won't boot.

After **Relaunch** (or a **Roll back**) the page shows a spinner and "waiting for it
to come back" while the station restarts, then refreshes itself to the new version —
you no longer need to reload it by hand. If it hasn't returned after ~90 seconds you
get a message to reload manually (a windowed station may need to be reopened).

This station is set to one update source (`updates.station_mode` in its config):
**online** stations show **Check for application updates**; **air-gapped** stations
hide that and show only **Install from file** (copy the release's `.ksupdate` +
`.zip` to USB). The other half is shown disabled with a one-line reason — that is
expected, not a fault.

- **"The last relaunch could not apply …"** — a red banner means the swap failed and
  the **previous version is still running**. Press **Relaunch** on the offer to try
  again; it usually clears on the second try. If it keeps failing, roll back to a
  known-good build and reinstall, or send a developer `data/launcher.log` from the
  station.

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
