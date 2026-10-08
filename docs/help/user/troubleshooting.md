# Troubleshooting

## "Station not ready" / link down
The lamp in the top bar is amber/red. The LabVIEW controller link is down.
- Check the broker (Mosquitto) is running.
- Check the LabVIEW Bridge is started.
- Open **Health** for a detailed verdict + what-to-do steps.

![Diagnostics — live event tail and station readiness](asset:diagnostics)

![Logs — error diagnostics and the action audit trail](asset:logs)

## Who did what / why did it fail?
The **Logs** page keeps an **action log** (every sign-in, setting, recipe, instrument and run change - who, what, and
whether it worked) and an **error log** (failed instrument commands, rejected or failed requests, aborted runs with the
reason). A run that the *system* ended - recipe could not be loaded, validation failed, timeout, safety trip - shows as
a **failure**; a run you aborted yourself does not.

## A run won't start
- **Blocked by MES** — the unit didn't pass the previous stage (see the message). Check MES config.
- **No recipe** — the barcode didn't resolve to a recipe; pick a recipe directly.
- **Controller offline** — see "link down" above.

## Live values not updating
Controller offline, or the variable isn't being published. Check Health → Production Systems.

## Maintenance won't turn on
The controller is the authority and must confirm. It refuses while a run is active. You also need **HEALTH.MAINTENANCE**.

## I can't see a screen / button
It's a permission. Ask a super_admin to grant it on the **Permissions** page; then **log out and back in** (permissions resolve at login).

## Test connection says "unavailable"
The LabVIEW bridge is offline, so the device can't be probed. Bring the controller online and retry.

## Still stuck
Use **Health** (Engineer view) for raw errors, and the **Debug Server** (dev tool) for a correlated cross-language timeline. Contact your system integrator with the run id / serial.
