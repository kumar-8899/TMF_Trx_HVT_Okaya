# Maintenance Console

Hands-on hardware operation. **Maintenance mode is owned by the LabVIEW controller** — the web only requests it.

## Enter / exit
- Press **Enter maintenance** (with a reason). The controller accepts or refuses (it refuses while a run is active).
- The mode indicator flips only when the controller confirms.

## What it gates
- **Read** variables any time.
- **Write** variables and run **disruptive** health checks **only while maintenance is on**.

## If it won't turn on
- The controller must be online and answer the request.
- You need the **HEALTH.MAINTENANCE** permission.
- See Troubleshooting for the MQTT details.
