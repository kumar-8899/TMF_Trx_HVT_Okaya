import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../../api/client";
import { PdfViewer } from "./PdfViewer";

const DOC = { id: "doc-9", title: "Wiring drawing", filename: "wiring.pdf" };

beforeEach(() => {
  (URL as any).createObjectURL = vi.fn(() => "blob:viewer");
  (URL as any).revokeObjectURL = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("PdfViewer", () => {
  it("fetches the PDF with auth and shows it via a blob: URL in an iframe", async () => {
    const blob = vi.spyOn(api, "getBlob").mockResolvedValue(new Blob(["%PDF-1.4"]));
    render(<PdfViewer doc={DOC} onClose={() => {}} />);
    const frame = await screen.findByTitle("PDF: Wiring drawing");
    expect(frame).toHaveAttribute("src", "blob:viewer");
    expect(blob).toHaveBeenCalledWith("/portal/library/doc-9/file");
    expect(screen.getByText("wiring.pdf")).toBeInTheDocument();
  });

  it("releases the blob URL when closed", async () => {
    vi.spyOn(api, "getBlob").mockResolvedValue(new Blob(["%PDF-"]));
    const { rerender } = render(<PdfViewer doc={DOC} onClose={() => {}} />);
    await screen.findByTitle("PDF: Wiring drawing");
    rerender(<PdfViewer doc={null} onClose={() => {}} />);
    await waitFor(() => expect((URL as any).revokeObjectURL).toHaveBeenCalledWith("blob:viewer"));
  });

  it("saves a copy through the backend (a blob download is invisible in the native window)", async () => {
    vi.spyOn(api, "getBlob").mockResolvedValue(new Blob(["%PDF-"]));
    const get = vi.spyOn(api, "get").mockResolvedValue({ saved: true, path: "C:/Users/op/Downloads/wiring-2026.pdf" });
    render(<PdfViewer doc={DOC} onClose={() => {}} />);
    await screen.findByTitle("PDF: Wiring drawing");
    fireEvent.click(screen.getByText("Save a copy"));
    expect(await screen.findByText("C:/Users/op/Downloads/wiring-2026.pdf")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/portal/library/doc-9/file?save=true");
  });

  it("shows the server's message when the document can't be loaded", async () => {
    vi.spyOn(api, "getBlob").mockRejectedValue(new ApiError(404, { detail: "No such document." }));
    render(<PdfViewer doc={DOC} onClose={() => {}} />);
    expect(await screen.findByText("No such document.")).toBeInTheDocument();
    expect(screen.queryByTitle("PDF: Wiring drawing")).not.toBeInTheDocument();
  });

  it("calls onClose from the close button", async () => {
    vi.spyOn(api, "getBlob").mockResolvedValue(new Blob(["%PDF-"]));
    const onClose = vi.fn();
    render(<PdfViewer doc={DOC} onClose={onClose} />);
    fireEvent.click(await screen.findByLabelText("close viewer"));
    expect(onClose).toHaveBeenCalled();
  });
});
