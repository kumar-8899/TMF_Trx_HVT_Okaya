import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { resetHelpImageCache } from "./HelpImage";
import { Markdown, slugify } from "./Markdown";
import { registerWidget } from "./widgets";

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search + loc.hash}</div>;
}

function renderMd(md: string) {
  return render(
    <MemoryRouter initialEntries={["/x"]}>
      <Routes>
        <Route path="*" element={<><Markdown>{md}</Markdown><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resetHelpImageCache();
  (URL as any).createObjectURL = vi.fn(() => "blob:mock");
});
afterEach(() => vi.restoreAllMocks());

describe("Markdown — help conventions", () => {
  it("gives headings stable anchor ids", () => {
    renderMd("## Ownership boundary — the rule!\n");
    expect(screen.getByRole("heading", { level: 2 })).toHaveAttribute("id", slugify("Ownership boundary — the rule!"));
    expect(slugify("Ownership boundary — the rule!")).toBe("ownership-boundary-the-rule");
  });

  it("routes help: links in-app instead of navigating away", async () => {
    renderMd("[the principles](help:dev-principles#locked-decisions)");
    fireEvent.click(screen.getByText("the principles"));
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent("/help?page=dev-principles#locked-decisions"));
  });

  it("opens external links in a new tab safely", () => {
    renderMd("[docs](https://example.com/x)");
    const a = screen.getByText("docs");
    expect(a).toHaveAttribute("target", "_blank");
    expect(a.getAttribute("rel")).toContain("noopener");
  });

  it("renders asset: images through the authenticated blob route with capture badge + stale warning", async () => {
    const get = vi.spyOn(api, "get").mockResolvedValue([
      { id: "dashboard", alt: "Dashboard", audience: "both", framework_version: "1.23.0", route: "/", stale: true },
    ]);
    const blob = vi.spyOn(api, "getBlob").mockResolvedValue(new Blob(["png"]));
    renderMd("![The dashboard](asset:dashboard)");
    const img = await screen.findByAltText("The dashboard");
    expect(img).toHaveAttribute("src", "blob:mock");
    expect(blob).toHaveBeenCalledWith("/help/asset/dashboard");
    expect(get).toHaveBeenCalledWith("/help/assets");
    expect(await screen.findByText("captured at v1.23.0")).toBeInTheDocument();
    expect(screen.getByText("screen changed since capture")).toBeInTheDocument();
  });

  it("shows a warning, not a broken image, when an asset is unavailable", async () => {
    vi.spyOn(api, "get").mockResolvedValue([]);
    vi.spyOn(api, "getBlob").mockRejectedValue(new Error("404"));
    renderMd("![x](asset:gone)");
    expect(await screen.findByText(/is not available/)).toBeInTheDocument();
  });

  it("dispatches ```tmf:<widget> blocks to the registry, passing the block body as the argument", () => {
    registerWidget("demo", ({ arg }) => <div>demo widget got: {arg}</div>);
    renderMd("```tmf:demo\nmodules\n```");
    expect(screen.getByText("demo widget got: modules")).toBeInTheDocument();
  });

  it("fails loudly for an unknown widget directive", () => {
    renderMd("```tmf:not-a-widget\n```");
    expect(screen.getByText(/Unknown help widget/)).toBeInTheDocument();
    expect(screen.getByText("tmf:not-a-widget")).toBeInTheDocument();
  });

  it("puts a copy button on ordinary code blocks", () => {
    renderMd("```bash\npython station.py\n```");
    expect(screen.getByLabelText("copy code")).toBeInTheDocument();
    expect(screen.getByText("python station.py")).toBeInTheDocument();
  });
});
