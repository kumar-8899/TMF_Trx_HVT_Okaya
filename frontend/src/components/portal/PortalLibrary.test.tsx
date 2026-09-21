import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../../api/client";
import { PortalLibrary, type LibDoc } from "./PortalLibrary";

let perms: string[] = [];
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ can: (p: string) => perms.includes(p) }) }));

const doc = (over: Partial<LibDoc> = {}): LibDoc => ({
  id: "doc-1", title: "Tenma 72-13360 manual", filename: "tenma.pdf", bytes: 250_000, tags: ["tenma", "psu"],
  description: "Bench supply", uploaded_by: "ulla", ts: 1_780_000_000, source: "upload", pages: 42, searchable: true,
  ...over,
});
const SEED = doc({ id: "seed-acme-relay", title: "Relay board drawing", source: "bundled", tags: ["bundled"], uploaded_by: null });

function mockGet(list: LibDoc[], extra: Record<string, unknown> = {}) {
  return vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path in extra) return extra[path];
    if (path.startsWith("/portal/library/search")) return { hits: [] };
    if (path === "/portal/library") return list;
    return null;
  });
}

beforeEach(() => { (URL as any).createObjectURL = vi.fn(() => "blob:pdf"); (URL as any).revokeObjectURL = vi.fn(); });
afterEach(() => { vi.restoreAllMocks(); perms = []; });

describe("PortalLibrary — permissions", () => {
  it("a viewer can read but sees no upload/edit/delete controls", async () => {
    perms = ["PORTAL.VIEW"];
    mockGet([doc()]);
    render(<PortalLibrary />);
    await screen.findByText("Tenma 72-13360 manual");
    expect(screen.getByLabelText("open Tenma 72-13360 manual")).toBeInTheDocument();
    expect(screen.queryByText("Add PDF")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^edit /)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^delete /)).not.toBeInTheDocument();
  });

  it("an uploader can add and edit but not delete; a manager can delete", async () => {
    perms = ["PORTAL.VIEW", "PORTAL.UPLOAD"];
    mockGet([doc()]);
    const { unmount } = render(<PortalLibrary />);
    await screen.findByText("Tenma 72-13360 manual");
    expect(screen.getByText("Add PDF")).toBeInTheDocument();
    expect(screen.getByLabelText("edit Tenma 72-13360 manual")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^delete /)).not.toBeInTheDocument();
    unmount();

    perms = ["PORTAL.VIEW", "PORTAL.UPLOAD", "PORTAL.MANAGE"];
    render(<PortalLibrary />);
    await screen.findByText("Tenma 72-13360 manual");
    expect(screen.getByLabelText("delete Tenma 72-13360 manual")).toBeInTheDocument();
  });

  it("documents shipped with the app are labelled and read-only even for a manager", async () => {
    perms = ["PORTAL.VIEW", "PORTAL.UPLOAD", "PORTAL.MANAGE"];
    mockGet([SEED]);
    render(<PortalLibrary />);
    await screen.findByText("Relay board drawing");
    expect(screen.getByText("shipped with the app")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^edit /)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^delete /)).not.toBeInTheDocument();
  });

  it("flags scanned PDFs as not searchable", async () => {
    perms = ["PORTAL.VIEW"];
    mockGet([doc({ searchable: false })]);
    render(<PortalLibrary />);
    expect(await screen.findByText("not searchable")).toBeInTheDocument();
  });

  it("explains an empty library differently to uploaders and viewers", async () => {
    perms = ["PORTAL.VIEW"];
    mockGet([]);
    const { unmount } = render(<PortalLibrary />);
    expect(await screen.findByText(/Ask an engineer or admin/)).toBeInTheDocument();
    unmount();
    perms = ["PORTAL.VIEW", "PORTAL.UPLOAD"];
    render(<PortalLibrary />);
    expect(await screen.findByText(/Use “Add PDF”/)).toBeInTheDocument();
  });
});

describe("PortalLibrary — upload", () => {
  it("uploads the chosen PDF as a raw body with title and tags, then refreshes the list", async () => {
    perms = ["PORTAL.VIEW", "PORTAL.UPLOAD"];
    const get = mockGet([]);
    const post = vi.spyOn(api, "postRaw").mockResolvedValue(doc());
    render(<PortalLibrary />);
    await screen.findByText(/Use “Add PDF”/);

    const file = new File([new Uint8Array([37, 80, 68, 70])], "Bench_wiring.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("choose a PDF"), { target: { files: [file] } });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Title")).toHaveValue("Bench wiring");          // prettified from the filename
    fireEvent.change(within(dialog).getByLabelText("Tags (comma separated)"), { target: { value: "wiring, psu" } });
    fireEvent.click(within(dialog).getByText("Upload"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [path, body, ctype] = post.mock.calls[0];
    expect(String(path)).toContain("/portal/library?");
    expect(String(path)).toContain("filename=Bench_wiring.pdf");
    expect(String(path)).toContain("tags=wiring%2C+psu");
    expect(body).toBe(file);
    expect(ctype).toBe("application/pdf");
    await screen.findByText(/Added “Bench wiring”/);
    expect(get.mock.calls.filter((c) => c[0] === "/portal/library").length).toBeGreaterThanOrEqual(2);   // refreshed
  });

  it("shows the server's reason when an upload is refused (e.g. a duplicate)", async () => {
    perms = ["PORTAL.VIEW", "PORTAL.UPLOAD"];
    mockGet([]);
    vi.spyOn(api, "postRaw").mockRejectedValue(new ApiError(409, { title: "Conflict", detail: "This PDF is already in the library as 'X'." }));
    render(<PortalLibrary />);
    await screen.findByText(/Use “Add PDF”/);
    fireEvent.change(screen.getByLabelText("choose a PDF"), { target: { files: [new File(["x"], "a.pdf")] } });
    fireEvent.click(within(await screen.findByRole("dialog")).getByText("Upload"));
    expect((await screen.findAllByText(/already in the library/)).length).toBeGreaterThan(0);
  });
});

describe("PortalLibrary — search, view, delete", () => {
  it("searches PDF contents and opens the hit in the viewer", async () => {
    perms = ["PORTAL.VIEW"];
    const get = mockGet([doc()], {
      "/portal/library/search?q=fuse": { hits: [{ id: "doc-1", title: "Tenma 72-13360 manual", snippet: "Replace [fuse] F3" }] },
    });
    const blob = vi.spyOn(api, "getBlob").mockResolvedValue(new Blob(["%PDF-"]));
    render(<PortalLibrary />);
    await screen.findByText("Tenma 72-13360 manual");
    fireEvent.change(screen.getByLabelText("search library"), { target: { value: "fuse" } });
    fireEvent.click(await screen.findByText(/Replace \[fuse\] F3/, undefined, { timeout: 3000 }));
    await waitFor(() => expect(blob).toHaveBeenCalledWith("/portal/library/doc-1/file"));
    const frame = await screen.findByTitle("PDF: Tenma 72-13360 manual");
    expect(frame).toHaveAttribute("src", "blob:pdf");
    expect(get).toHaveBeenCalledWith("/portal/library/search?q=fuse");
  });

  it("says so when nothing matches", async () => {
    perms = ["PORTAL.VIEW"];
    mockGet([doc()]);
    render(<PortalLibrary />);
    await screen.findByText("Tenma 72-13360 manual");
    fireEvent.change(screen.getByLabelText("search library"), { target: { value: "zzz" } });
    expect(await screen.findByText(/No matches for “zzz”/, undefined, { timeout: 3000 })).toBeInTheDocument();
  });

  it("deletes only after confirmation", async () => {
    perms = ["PORTAL.VIEW", "PORTAL.MANAGE"];
    mockGet([doc()]);
    const del = vi.spyOn(api, "del").mockResolvedValue({ deleted: "doc-1" });
    const confirm = vi.spyOn(window, "confirm");
    render(<PortalLibrary />);
    await screen.findByText("Tenma 72-13360 manual");

    confirm.mockReturnValueOnce(false);
    fireEvent.click(screen.getByLabelText("delete Tenma 72-13360 manual"));
    expect(del).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByLabelText("delete Tenma 72-13360 manual"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/portal/library/doc-1"));
    await screen.findByText(/Deleted “Tenma 72-13360 manual”/);
  });
});
