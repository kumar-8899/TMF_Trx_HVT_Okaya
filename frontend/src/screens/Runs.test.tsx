import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import { Runs } from "./Runs";

const OPERATOR = { username: "op", role: "operator", permissions: ["TEST.RUN"] };
const PROFILE = { live_variables: [], ui: { verdict_banner: true, message_line: true, today_strip: true } };
const BARCODE_CFG = { enabled: true, length: 8, parts: [
  { name: "model", start: 0, length: 3 }, { name: "serial", start: 3, length: 5 }],
  recipe_part: "model" };

function baseRoutes(barcodeCfg: any) {
  return {
    "GET /auth/me": { body: OPERATOR },
    "GET /runs": { body: [] },
    "GET /runs/config": { body: PROFILE },
    "GET /config/barcode": { body: barcodeCfg },
    "GET /config/shift/current": { body: { enabled: false } },
    "GET /recipes": { body: [{ recipe_id: "inv", name: "Inverter" }] },
  };
}

async function openStartDialog() {
  render(<AuthProvider><Runs /></AuthProvider>);
  await userEvent.click(await screen.findByRole("button", { name: "Start test" }));
}

afterEach(() => localStorage.clear());

describe("Runs — Start dialog driven by Config → Barcode", () => {
  it("barcode enabled: shows only the serial field, previews the recipe part, and POSTs {barcode}", async () => {
    localStorage.setItem("tmf.token", "t");
    let posted: any = null;
    globalThis.fetch = (async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url).split("?")[0];
      const routes: Record<string, any> = baseRoutes(BARCODE_CFG);
      if (method === "POST" && path === "/runs/start") {
        posted = JSON.parse(opts.body);
        return { ok: true, status: 200, text: async () => JSON.stringify({ run_id: "r1", recipe_id: "INV", serial_no: "INV12345" }) } as Response;
      }
      const route = routes[`GET ${path}`];
      return route
        ? { ok: true, status: 200, text: async () => JSON.stringify(route.body) } as Response
        : { ok: false, status: 404, text: async () => "" } as Response;
    }) as any;

    await openStartDialog();
    expect(screen.getByLabelText("Serial number")).toBeInTheDocument();
    expect(screen.queryByLabelText("Recipe")).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Serial number"), "INV12345");
    expect(screen.getByText("INV")).toBeInTheDocument();   // live preview, sliced at the model part

    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(posted).toEqual({ barcode: "INV12345" }));
  });

  it("Enter in the serial field does NOT start the run when submit_on_enter is absent/false " +
     "(framework-fix-prompt-2.md Issue 1) — a real scanner appends Enter to every scan, so " +
     "'scan' and 'start the test' must not be the same action by default", async () => {
    localStorage.setItem("tmf.token", "t");
    let posted: any = null;
    globalThis.fetch = (async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url).split("?")[0];
      const routes: Record<string, any> = baseRoutes(BARCODE_CFG);
      if (method === "POST" && path === "/runs/start") {
        posted = JSON.parse(opts.body);
        return { ok: true, status: 200, text: async () => JSON.stringify({ run_id: "r1" }) } as Response;
      }
      const route = routes[`GET ${path}`];
      return route
        ? { ok: true, status: 200, text: async () => JSON.stringify(route.body) } as Response
        : { ok: false, status: 404, text: async () => "" } as Response;
    }) as any;

    await openStartDialog();
    const field = screen.getByLabelText("Serial number");
    await userEvent.type(field, "INV12345{Enter}");
    // dialog stays open, nothing posted — the operator must still click Start
    expect(posted).toBeNull();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Serial number")).toHaveValue("INV12345");
  });

  it("Enter DOES start the run when submit_on_enter is true (opt-in)", async () => {
    localStorage.setItem("tmf.token", "t");
    let posted: any = null;
    const cfg = { ...BARCODE_CFG, submit_on_enter: true };
    globalThis.fetch = (async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url).split("?")[0];
      const routes: Record<string, any> = baseRoutes(cfg);
      if (method === "POST" && path === "/runs/start") {
        posted = JSON.parse(opts.body);
        return { ok: true, status: 200, text: async () => JSON.stringify({ run_id: "r1" }) } as Response;
      }
      const route = routes[`GET ${path}`];
      return route
        ? { ok: true, status: 200, text: async () => JSON.stringify(route.body) } as Response
        : { ok: false, status: 404, text: async () => "" } as Response;
    }) as any;

    await openStartDialog();
    await userEvent.type(screen.getByLabelText("Serial number"), "INV12345{Enter}");
    await waitFor(() => expect(posted).toEqual({ barcode: "INV12345" }));
  });

  it("barcode disabled: shows only the recipe dropdown and POSTs {recipe_id}", async () => {
    localStorage.setItem("tmf.token", "t");
    let posted: any = null;
    const disabledCfg = { ...BARCODE_CFG, enabled: false };
    globalThis.fetch = (async (url: any, opts: any = {}) => {
      const method = (opts.method || "GET").toUpperCase();
      const path = String(url).split("?")[0];
      const routes: Record<string, any> = baseRoutes(disabledCfg);
      if (method === "POST" && path === "/runs/start") {
        posted = JSON.parse(opts.body);
        return { ok: true, status: 200, text: async () => JSON.stringify({ run_id: "r1", recipe_id: "inv" }) } as Response;
      }
      const route = routes[`GET ${path}`];
      return route
        ? { ok: true, status: 200, text: async () => JSON.stringify(route.body) } as Response
        : { ok: false, status: 404, text: async () => "" } as Response;
    }) as any;

    await openStartDialog();
    expect(screen.queryByLabelText("Serial number")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Recipe")).toBeInTheDocument());

    await userEvent.click(screen.getByLabelText("Recipe"));
    await userEvent.click(await screen.findByRole("option", { name: /Inverter/ }));
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(posted).toEqual({ recipe_id: "inv" }));
  });
});
