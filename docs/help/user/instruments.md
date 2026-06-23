# Instruments (Config)

Set up the station's instruments and test their connection. The actual device I/O is handled by LabVIEW — here you capture the **connection profile**.

## Add / edit an instrument
1. **Add instrument**, give it an **id** (lowercase, fixed once created) and a **label**.
2. Pick a **transport** (VISA, Modbus TCP/RTU, CAN, NI-DAQmx, Serial, Raw TCP). The form shows the fields that transport needs.
3. Fill the fields; a **resource preview** shows the resulting address string.
4. **Test connection** — asks LabVIEW to open the device. If the controller is offline you'll see **unavailable** (honest, not a hang).
5. **Family / capabilities** feed the health checks for this instrument.

Adding a new instrument type later is a backend change (one catalog entry) — the form adapts automatically.
