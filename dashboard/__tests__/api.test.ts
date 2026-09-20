import { beforeEach, describe, expect, it, vi } from "vitest";
import { addNote, exportUrl, listContent, updateStatus } from "@/lib/api";

describe("exportUrl", () => {
  it("builds a URL for each supported format", () => {
    expect(exportUrl("json")).toContain("/api/exports/json");
    expect(exportUrl("csv")).toContain("/api/exports/csv");
    expect(exportUrl("markdown")).toContain("/api/exports/markdown");
  });
});

describe("listContent", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ items: [], total: 0, page: 1, limit: 50 }),
      })
    );
  });

  it("omits empty filter params from the query string", async () => {
    await listContent({ platform: "", status: "Approved" });
    const calledUrl = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(calledUrl).toContain("status=Approved");
    expect(calledUrl).not.toContain("platform=");
  });

  it("throws a clear error on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(listContent()).rejects.toThrow(/500/);
  });
});

describe("write helpers call the local proxy routes, never the backend directly", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ id: "1" }),
      })
    );
  });

  it("updateStatus posts to /api/proxy/content/{id}/status", async () => {
    await updateStatus("abc", "Approved");
    const [url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/proxy/content/abc/status");
    expect(options.method).toBe("PATCH");
  });

  it("addNote posts to /api/proxy/content/{id}/notes", async () => {
    await addNote("abc", "hello");
    const [url, options] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/proxy/content/abc/notes");
    expect(options.method).toBe("POST");
  });
});
