import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../../test/fetchMock";
import { OkayaMaintenance } from "./OkayaMaintenance";

vi.mock("../../../auth/AuthContext", async (importOriginal) => {
  const principal = { username: "admin", role: "super_admin", permissions: ["MAINTENANCE.*"] };
  return { ...(await importOriginal<typeof import("../../../auth/AuthContext")>()), useAuth: () => ({ principal }) };
});

const routes = () => ({
  "GET /variables/instances": { body: ["hipot", "relay1", "relay2"].map((id) => ({ id, state: "connected" })) },
  "POST /variables/instances/relay1/call": { body: { result: null } },
  "POST /variables/instances/relay2/call": { body: { result: null } },
  "POST /variables/instances/hipot/call": { body: { result: [0.05, false] } },
});

const relayWrites = (fetch: any) =>
  (fetch.mock.calls as any[])
    .filter(([url, o]) => String(url) === "/variables/instances/relay1/call" && o?.method === "POST")
    .map(([, o]) => JSON.parse(o.body).args as [number, boolean]);

describe("Maintenance → Start Test", () => {
  it("opens the route again after the test (the contactor must not stay energised)", async () => {
    const fetch = mockFetch(routes());
    render(<OkayaMaintenance />);
    await userEvent.click(await screen.findByRole("button", { name: /start test/i }));
    await waitFor(() => expect(relayWrites(fetch)).toEqual([[0, true], [0, false]]));
  });

  it("a second test on another route leaves nothing energised either", async () => {
    const fetch = mockFetch(routes());
    render(<OkayaMaintenance />);
    const start = await screen.findByRole("button", { name: /start test/i });
    await userEvent.click(start);
    await waitFor(() => expect(relayWrites(fetch)).toHaveLength(2));
    await userEvent.click(await screen.findByRole("button", { name: /start test/i }));
    await waitFor(() => expect(relayWrites(fetch)).toEqual([[0, true], [0, false], [0, true], [0, false]]));
  });
});
