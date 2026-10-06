# MES interlock (Config)

Cross-station gate: block a unit unless it passed the previous stage, and send this stage's result on for the next one. Open **Config → MES** (needs the *Station settings* permission).

![MES interlock — cross-station gate and publish](asset:config-mes)

## Pick the transport

- **Folder** — stations hand PASS / FAIL files to each other through a shared folder.
- **Database** — your MES lives in a database (MySQL or SQL Server). *Inbound* reads a status column of a table; *Outbound* writes one row per finished run into one table. Each direction has its own **On / Off** switch — switch one off and its settings are kept but nothing is checked or sent.

Two safety choices apply to both:

- **No MES record found** — what to do when the unit isn't known to MES: *Block the run* (default) or *Allow the run*.
- **MES unreachable / error** — what to do when the database can't be read (down, wrong password, timeout): *Block the run* (default) or *Allow the run*. The operator sees the reason on the screen.

## Inbound — the gate (Database)

Work down the steps; each one unlocks the next. The gate only **reads** your database — it never writes or creates anything there.

1. **Server** — provider, host, port, user, password, then **Test connection**. A saved password is shown as `•••••• (unchanged)`; leave it blank to keep it.
2. **Database** — pick one from the list the server offers.
3. **Table** — pick a table or view. For a table outside the default schema, write `schema.table`.
4. **Columns** — the **serial number column** (where the unit's barcode is stored), the **status column** (where the previous stage's result is stored) and the **allow value**. A unit is allowed **only if its status equals the allow value — anything else blocks**. The list under *Allow value* shows the values actually found in the status column. Case and surrounding spaces are ignored unless you untick it. **Verify names** checks the names against the table.
5. **Latest by** — if the table keeps several rows per unit (a history), the **newest** row decides. Choose the column that says how new a row is. If the date and the time are **separate columns**, add the date first, then the time ("Newest by *date*, then by *time*"). Leave it empty when a unit has one row; with several rows and no column here, *every* row must equal the allow value.
6. **Try a serial** — type a serial number to see exactly what the gate would do (rows found, ALLOWED / BLOCKED) before you switch it on.

Press **Save inbound**.

## Outbound — publish (Database)

The result goes to MES **the moment a run finishes**. It writes one row per run with the unit's details — serial, model, operator, recipe, result, start/finish time, business day, shift (the same details as the Reports table, without the individual test data).

1. **Server** — tick *Use the same server as inbound* if it is the same one.
2. **Database** — pick an existing one, or type a new name; a new database is created when you apply (needs permission to create databases).
3. **Table** — pick an existing table, or type a new name to create it.
4. **Columns** — for a **new** table the columns use the field names (you can rename them). For an **existing** table each field is matched to a column by name automatically; change any, or clear an optional one to skip it. `run_id`, `serial_no` and `result` are required — `run_id` is what lets a re-send replace a row instead of duplicating it.
5. **Apply** — **Check table** tells you if it fits (missing columns, required columns that aren't mapped, columns that must have a value but aren't mapped). **Create table / Apply** creates the table, or adds the missing columns when *Add missing columns* is ticked. Nothing is ever created while testing — only here.

Press **Save outbound**.

### If a result can't be sent

There is **no queue and no silent retry**. If the result of a finished run can't be delivered, a red prompt appears **on every screen**: *"A test result was NOT sent to MES"*, with the serial number and the database's reason. The next station will not see that unit until it is delivered.

- **Retry** sends it again (the row is rebuilt from the run's record, so nothing is duplicated). If it still fails, the prompt stays and shows the new reason.
- **Dismiss** gives up on delivering it — you are asked to confirm, and it is written to the audit log.
- **Remind me later** hides the prompt until another result fails.

## When the lists are empty — type the names

Some servers don't let the user list databases, tables or columns. If the list can't be loaded, the field shows *"Couldn't list … — type the name"* and accepts what you type. Use **Verify names** (inbound) or **Check table** (outbound) to confirm the names before you rely on them.

## Notes

- Passwords are stored on this PC and never shown again.
- SQL Server needs the Windows *ODBC Driver 18 for SQL Server*.
- Requires the MES module to be enabled.
