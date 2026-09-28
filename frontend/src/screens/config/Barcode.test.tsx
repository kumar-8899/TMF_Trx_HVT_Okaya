import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { AuthProvider } from "../../auth/AuthContext";
import { mockFetch } from "../../test/fetchMock";
import { ConfigBarcode } from "./Barcode";

const EDITOR = { username: "eng", role: "engineer", permissions: ["CONFIG.EDIT", "CONFIG.VIEW"] };
const VIEWER = { username: "op", role: "operator", permissions: ["CONFIG.VIEW"] };
const SAVED_CFG = { enabled: true, length: 8, parts: [
  { name: "model", start: 0, length: 3 }, { name: "serial", start: 3, length: 5 }],
  recipe_part: "model" };

afterEach(() => localStorage.clear());

describe("ConfigBarcode", () => {
  it("view-only: no Save/Add-part controls without CONFIG.EDIT", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({ "GET /auth/me": { body: VIEWER }, "GET /config/barcode": { body: SAVED_CFG } });
    render(<AuthProvider><ConfigBarcode /></AuthProvider>);
    await waitFor(() => expect(screen.getByDisplayValue("model")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add part/i })).not.toBeInTheDocument();
  });

  it("adds and removes a part row, and Save stays disabled until dirty", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({ "GET /auth/me": { body: EDITOR }, "GET /config/barcode": { body: SAVED_CFG } });
    render(<AuthProvider><ConfigBarcode /></AuthProvider>);
    await waitFor(() => expect(screen.getByDisplayValue("model")).toBeInTheDocument());
    const save = () => screen.getByRole("button", { name: "Save" });
    expect(save()).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /add part/i }));
    expect(save()).not.toBeDisabled();
    expect(screen.getAllByLabelText(/^part_name_/)).toHaveLength(3);

    const rows = screen.getAllByRole("row");
    const newRow = rows[rows.length - 1];   // header + model + serial + the newly added row
    await userEvent.click(within(newRow).getByRole("button"));   // its delete IconButton
    expect(screen.getAllByLabelText(/^part_name_/)).toHaveLength(2);
  });

  it("designates a part as the recipe id via the radio control, and Save PUTs it", async () => {
    localStorage.setItem("tmf.token", "t");
    let putBody: any = null;
    globalThis.fetch = (async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url);
      if (path === "/auth/me") return { ok: true, status: 200, text: async () => JSON.stringify(EDITOR) } as Response;
      if (path === "/config/barcode" && method === "PUT") {
        putBody = JSON.parse(opts.body);
        return { ok: true, status: 200, text: async () => JSON.stringify(putBody) } as Response;
      }
      if (path === "/config/barcode") return { ok: true, status: 200, text: async () => JSON.stringify(SAVED_CFG) } as Response;
      return { ok: false, status: 404, text: async () => "" } as Response;
    }) as any;

    render(<AuthProvider><ConfigBarcode /></AuthProvider>);
    await waitFor(() => expect(screen.getByDisplayValue("serial")).toBeInTheDocument());
    const radios = screen.getAllByRole("radio");
    await userEvent.click(radios[1]);   // the "serial" row's radio
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody.recipe_part).toBe("serial");
  });

  it("submit-on-scan is off by default, and Save PUTs it on when toggled " +
     "(framework-fix-prompt-2.md Issue 1 — opt-in, not the unconditional default)", async () => {
    localStorage.setItem("tmf.token", "t");
    let putBody: any = null;
    globalThis.fetch = (async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url);
      if (path === "/auth/me") return { ok: true, status: 200, text: async () => JSON.stringify(EDITOR) } as Response;
      if (path === "/config/barcode" && method === "PUT") {
        putBody = JSON.parse(opts.body);
        return { ok: true, status: 200, text: async () => JSON.stringify(putBody) } as Response;
      }
      if (path === "/config/barcode") return { ok: true, status: 200, text: async () => JSON.stringify(SAVED_CFG) } as Response;
      return { ok: false, status: 404, text: async () => "" } as Response;
    }) as any;

    render(<AuthProvider><ConfigBarcode /></AuthProvider>);
    await waitFor(() => expect(screen.getByDisplayValue("model")).toBeInTheDocument());
    const toggle = screen.getByRole("checkbox", { name: /submit on enter|submit.on.scan/i });
    expect(toggle).not.toBeChecked();

    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(putBody).not.toBeNull());
    expect(putBody.submit_on_enter).toBe(true);
  });

  it("surfaces a validation error from the backend", async () => {
    localStorage.setItem("tmf.token", "t");
    mockFetch({
      "GET /auth/me": { body: EDITOR },
      "GET /config/barcode": { body: { enabled: false, length: 0, parts: [], recipe_part: null } },
      "PUT /config/barcode": { status: 400, body: { detail: "length must be >= 1" } },
    });
    render(<AuthProvider><ConfigBarcode /></AuthProvider>);
    await waitFor(() => expect(screen.getByLabelText("barcode_length")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /add part/i }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("length must be >= 1")).toBeInTheDocument());
  });
});
