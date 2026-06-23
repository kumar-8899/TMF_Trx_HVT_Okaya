# MES interlock (Config)

Cross-station gate: block a unit unless it passed the previous stage, and publish this stage's result for the next.

- **Inbound gate** — when on, a run is blocked unless the unit passed upstream.
- **Outbound publish** — when on, this stage's result is written downstream on run finish.
- The transport (folder/db/xml) and stage are shown.

Moved here from Settings. Requires the MES module to be enabled.
