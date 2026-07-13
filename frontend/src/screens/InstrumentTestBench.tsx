import { PageHeader } from "../components/ui";
import { InstrumentControlPanel } from "../components/testing/InstrumentControlPanel";

/** Instrument Test Bench — a dedicated hands-on hardware page. Drives Python-owned
 * library instruments through their capability methods (the UI form of the bring-up
 * probing done in Python). Python-owned instruments are driven directly by the app,
 * so there is no maintenance-mode gate; access is gated by the HEALTH.MAINTENANCE
 * permission on the route. */
export function InstrumentTestBench() {
  return (
    <div>
      <PageHeader title="Instrument Test Bench" subtitle="Hands-on manual control of Python-owned instruments" />
      <InstrumentControlPanel />
    </div>
  );
}
