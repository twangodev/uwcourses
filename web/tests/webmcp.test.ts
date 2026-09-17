import { afterEach, describe, expect, it, vi } from "vitest";
import { courseTools, registerCourseTools } from "../../src/lib/webmcp";

const signal = new AbortController().signal;
function execute(name: string, input: Record<string, unknown>) {
  return courseTools
    .find((tool) => tool.name === name)!
    .execute(input, { signal });
}
afterEach(() => vi.unstubAllGlobals());

describe("WebMCP course tools", () => {
  it("uses the existing search contract and forwards cancellation", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(Response.json({ items: [], page: 2 }));
    vi.stubGlobal("fetch", fetch);
    expect(
      await execute("search_courses", {
        q: "CS 300",
        page: 2,
        availability: "all",
      }),
    ).toBe('{"items":[],"page":2}');
    expect(fetch).toHaveBeenCalledWith(
      "/api/search?q=CS+300&availability=all&page=2&kind=course",
      {
        signal,
        headers: { Accept: "application/json" },
      },
    );
  });

  it.each(["COMPSCI 300", "COMPSCI_300"])(
    "resolves course code %s to its JSON document",
    async (course) => {
      const fetch = vi.fn().mockResolvedValue(Response.json({ course: {} }));
      vi.stubGlobal("fetch", fetch);
      await execute("get_course", { course });
      expect(fetch.mock.calls[0][0]).toBe("/courses/COMPSCI_300.json");
    },
  );

  it("uses dataset UIDs and filters for grade history", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ rows: [] }));
    vi.stubGlobal("fetch", fetch);
    await execute("get_course_grades", {
      course_uid: "course_123",
      term: "1272",
      page: 3,
    });
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/courses/course_123/grades?term=1272&page=3",
    );
  });

  it.each([
    ["search_courses", { page: -1 }],
    ["search_courses", { term: "fall" }],
    ["search_courses", { kind: "instructor" }],
    ["get_course", { course: "../../api/status" }],
    ["get_course_grades", { course_uid: "../status" }],
  ])("rejects invalid %s input before fetching", async (name, input) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      execute(name as string, input as Record<string, unknown>),
    ).rejects.toThrow("Invalid tool input");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("reports missing courses and non-JSON redirects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("missing", { status: 404 })),
    );
    await expect(execute("get_course", { course: "CS_300" })).rejects.toThrow(
      "404",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>Search</html>", {
          headers: { "content-type": "text/html" },
        }),
      ),
    );
    await expect(execute("get_course", { course: "CS_300" })).rejects.toThrow(
      "ambiguous",
    );
  });

  it("does nothing when the browser lacks WebMCP", () => {
    vi.stubGlobal("document", {});
    expect(registerCourseTools()).toBeTypeOf("function");
  });

  it("registers once and unregisters on disposal", async () => {
    const registerTool = vi.fn().mockResolvedValue(undefined);
    const dispose = registerCourseTools({
      registerTool,
    } as unknown as WebMCP.ModelContext);
    await vi.waitFor(() => expect(registerTool).toHaveBeenCalledTimes(3));
    const registrationSignal = registerTool.mock.calls[0][1].signal;
    expect(registrationSignal.aborted).toBe(false);
    dispose();
    expect(registrationSignal.aborted).toBe(true);
  });

  it("cleans up partial registration after failure", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const registerTool = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("unsupported"));
    registerCourseTools({ registerTool } as unknown as WebMCP.ModelContext);
    await vi.waitFor(() => expect(warn).toHaveBeenCalled());
    expect(registerTool.mock.calls[0][1].signal.aborted).toBe(true);
    expect(registerTool).toHaveBeenCalledTimes(2);
    warn.mockRestore();
  });
});
