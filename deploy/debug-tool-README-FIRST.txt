TMF Debug Tool - read this first
================================

WHAT IT IS
  A support tool for the engineer who maintains the test bench. It is NOT part of the test application: it is a separate program in
  this folder, it is never started by the application, it is not a Windows service, and it adds nothing to Windows startup.
  It only runs while an engineer has started it and keeps the window open.

WHAT IT CAN DO
  - Read what the application already records: its error/action logs, the launcher log, the MQTT messages on the local broker,
    the flight-recorder files, and the installed program's version and file hashes.
  - On request of the developer (Claude Code, over a token-protected connection the engineer switches on): read a text file under
    the application's folders (secrets masked), set a log level for a limited time, send ONE read-only command to an instrument
    through the running application, or run ONE script.
  - Pack the diagnostics into one zip file for a bench with no network path to the developer.

WHAT STOPS IT DOING MORE
  - Nothing on this PC is reachable until the operator presses "Turn sharing ON" (1 to 24 hours; it switches itself off).
  - The developer can READ what the application records. Anything that changes or runs something on this PC waits for the person at
    the PC to read the exact request and press Approve - once per request. No answer within 2 minutes = denied. Stop sharing denies
    everything waiting.
  - Scripts run as the signed-in Windows user (never elevated), with a time limit, capped output, secrets removed from their
    environment, one at a time, and never during a test run unless the approver explicitly allows it.
  - Instrument commands are limited to the read-only methods the application's own catalog lists; never set/enable/safe-state.
  - Every request, decision and result is written to access.jsonl (see "WHERE THINGS ARE").

NETWORK
  - Listens on ONE address and port chosen by the operator (default 127.0.0.1:8010; for a remote session the PC's VPN/LAN address).
    It refuses to listen on all interfaces.
  - Connects out only to the application's own MQTT broker (usually 127.0.0.1:1883) and the application's own web port on
    127.0.0.1 (usually 8000). It never contacts the internet.

TO CHECK THIS PC BEFORE ANY SESSION (about 30 seconds, uses a fake install, never touches the real application)
  tmf-debug-tool.exe selftest
  It reports, for example, a blocked port, a missing PowerShell, or a security product that stops the tool.

WHERE THINGS ARE
  This folder ................ the program (delete the folder to remove the tool completely)
  %LOCALAPPDATA%\TMF-Debug-Tool\access.jsonl ...... the audit log of every remote request and decision
  %LOCALAPPDATA%\TMF-Debug-Tool\scripts\ .......... every script that ran, with its output and SHA-256
  %LOCALAPPDATA%\TMF-Debug-Tool\bundles\ .......... diagnostic bundles created for download
  Desktop ................... bundles made with the Collect button (they can contain operator names and serial numbers;
                              passwords, tokens and database credentials are masked; delete them when the case is closed)

TO USE
  1. Double-click tmf-debug-tool.exe (or:  tmf-debug-tool.exe serve --state-dir "<folder that contains run.dist>").
  2. Share tab -> Turn sharing ON -> give the developer the command shown (it appears once and is not stored).
  3. Keep the window open; approve or deny requests on the Approvals tab. Closing the window stops everything.

  No connection to the developer? Collect tab -> "Collect now" -> send the one zip file.

SIGNING AND INTEGRITY
  The program is code-signed by the framework publisher when the release was built with a signing certificate; SHA256SUMS.txt
  (next to the downloaded zip) lists the checksum of the zip. An unsigned build may be blocked by Windows Smart App Control.
