# Support session (TMF Debug Tool)

If your service engineer has given you the **TMF Debug Tool**, it lets them (or the developer) find a fault on this bench without
being at the PC - or lets you send them one file when there is no network link. It is a separate program, **not part of this
application**: it never starts by itself, it is not a Windows service, and closing its window ends everything.

## What you control

- **Nothing is reachable until you turn sharing on.** *Share → Turn sharing ON* (1 to 24 hours; it switches itself off).
  You read the developer a one-line command - it is shown once and not stored.
- **You approve every change.** The developer can *read* what the application already records. Anything that **changes or runs
  something on this PC** - running a script, sending a command to an instrument, reading a file, raising a log level - appears on the
  **Approvals** tab with the exact request. Read it, then **Approve** or **Deny**. One click approves one request. If you do not
  answer within 2 minutes it is denied. **Stop sharing** denies everything that is waiting.
- **Scripts never run as administrator**, never while a test is running (unless you tick *allow during a test* on that card),
  one at a time, with a time limit.
- **Instrument commands are read-only** (identify, measurements). Nothing is ever set, switched on or put in a safe state this way.
- Everything is written to an audit log (`access.jsonl`) and shown on the **Share** tab.

## Start a session

1. Open the **TMF Debug Tool** (Start menu, or `tools\debug-tool\tmf-debug-tool.exe` in the application folder).
2. **First time only:** on the **Status** tab choose the folder where the application is installed (the one that contains `run.dist`), press **Check**, then **Use this folder**. The tool never guesses and remembers your choice. Until then it does nothing and sharing is refused.
3. **Share → Turn sharing ON**, then read the shown command to the developer. Keep the window open.
4. When a request arrives the **Approvals** tab opens and the window title shows a number. Read the request; **Approve** or **Deny**.
5. When you are done, **Stop sharing** and close the window.

## No connection to the developer?

Open the **Collect** tab and press **Collect now**. It writes **one zip file to your Desktop** with the application's recent
diagnostics (logs, recorder, installed versions, running programs, ODBC drivers). Send that file. It can contain operator names
and serial numbers (passwords and tokens are masked); delete it when the case is closed.

## Check this PC first

Before a session on a new PC, run `tmf-debug-tool.exe selftest` once (about 30 seconds). It uses a fake installation and does not
touch the real application. It names anything in the way: a blocked port, no PowerShell, or a security product stopping the tool.

## Good to know

- The tool only listens on the one address you start it on, and only connects to this application's own broker and web page.
- To remove it, delete its folder. It leaves nothing else behind.
- While a test is running the tool does not touch the instruments.
