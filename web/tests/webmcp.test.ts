import { afterEach, describe, expect, it, vi } from "vitest";
import {
  courseTools,
  createWebmcpTools,
  registerCourseTools,
} from "../../src/lib/webmcp";

const signal = new AbortController().signal;
function execute(
  name: string,
  input: Record<string, unknown>,
  tools = courseTools,
) {
  return tools.find((tool) => tool.name === name)!.execute(input, { signal });
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
      const fetch = vi.fn().mockResolvedValue(Response.json({ data: {} }));
      vi.stubGlobal("fetch", fetch);
      await execute("get_course", { course });
      expect(fetch.mock.calls[0][0]).toBe("/courses/COMPSCI_300.json");
    },
  );

  it("returns a compact course summary with a link to the full document", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          url: "https://uwcourses.com/courses/COMPSCI_300",
          data: {
            course: {
              course_id: "COMPSCI 300",
              course_uid: "course_1",
              title: "Programming II",
              description: "x".repeat(4000),
              requirements_text: "COMPSCI 200",
              credits_min: 3,
              credits_max: 3,
              semester: "1272",
              instructors: [
                {
                  name: "Ada",
                  instructor_uid: "i1",
                  instructor_url: "/instructors/ADA",
                },
              ],
              llm_topics: ["programming"],
            },
            following: [{ code: "COMPSCI 400", title: "Programming III" }],
            context: { evidence: "x".repeat(8000) },
          },
        }),
      ),
    );
    const result = JSON.parse(
      String(await execute("get_course", { course: "COMPSCI 300" })),
    );
    expect(result.course_id).toBe("COMPSCI 300");
    expect(result.document).toBe("/courses/COMPSCI_300.json");
    expect(result.instructors[0].instructor_url).toBe("/instructors/ADA");
    expect(result.context).toBeUndefined();
    expect(result.description.length).toBeLessThan(500);
    expect(JSON.stringify(result).length).toBeLessThan(2000);
  });

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
});

describe("WebMCP instructor and department tools", () => {
  it("searches instructors through the existing search contract", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(Response.json({ items: [], kind: "instructor" }));
    vi.stubGlobal("fetch", fetch);
    await execute("search_instructors", { q: "Hobbes", page: 2 });
    expect(fetch).toHaveBeenCalledWith(
      "/api/search?q=Hobbes&page=2&kind=instructor",
      {
        signal,
        headers: { Accept: "application/json" },
      },
    );
  });

  it.each(["HOBBES_LEGAULT", "/instructors/HOBBES_LEGAULT"])(
    "resolves instructor identifier %s to its JSON document",
    async (instructor) => {
      const fetch = vi.fn().mockResolvedValue(Response.json({ data: {} }));
      vi.stubGlobal("fetch", fetch);
      await execute("get_instructor", { instructor });
      expect(fetch.mock.calls[0][0]).toBe("/instructors/HOBBES_LEGAULT.json");
    },
  );

  it("returns a compact instructor summary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          url: "https://uwcourses.com/instructors/ADA",
          data: {
            instructor: {
              instructor_uid: "i1",
              name: "Ada",
              instructor_url: "/instructors/ADA",
              ratings: { quality: 4.5, quality_count: 12 },
            },
            history: Array.from({ length: 80 }, () => ({ term: "1272" })),
            courses: [{ course_id: "COMPSCI 300", title: "Programming II" }],
            reviews: { total: 40, items: [{ comment: "y".repeat(2000) }] },
          },
        }),
      ),
    );
    const result = JSON.parse(
      String(await execute("get_instructor", { instructor: "ADA" })),
    );
    expect(result.instructor_uid).toBe("i1");
    expect(result.document).toBe("/instructors/ADA.json");
    expect(result.history).toBeUndefined();
    expect(JSON.stringify(result).length).toBeLessThan(2000);
  });

  it("uses instructor UIDs for reviews, courses, and history", async () => {
    const fetch = vi
      .fn()
      .mockImplementation(() => Promise.resolve(Response.json({ items: [] })));
    vi.stubGlobal("fetch", fetch);
    await execute("get_instructor_reviews", {
      instructor_uid: "instr_1",
      course_uid: "course_1",
      page: 2,
    });
    await execute("get_instructor_courses", {
      instructor_uid: "instr_1",
      term: "1272",
    });
    await execute("get_instructor_history", {
      instructor_uid: "instr_1",
      page: 3,
    });
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/api/instructors/instr_1/reviews?course=course_1&page=2",
      "/api/instructors/instr_1/courses?term=1272",
      "/api/instructors/instr_1/history?page=3",
    ]);
  });

  it("lists departments from dataset status", async () => {
    const fetch = vi.fn().mockResolvedValue(
      Response.json({
        term: "1272",
        departments: [{ subject: "COMPSCI", count: 12 }],
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const result = JSON.parse(String(await execute("list_departments", {})));
    expect(fetch.mock.calls[0][0]).toBe("/api/status");
    expect(result.departments[0].subject).toBe("COMPSCI");
  });

  it("loads department and catalog documents", async () => {
    const fetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        Response.json({
          url: "https://uwcourses.com/departments/COMPSCI",
          data: {
            subject: "COMPSCI",
            results: {
              total: 2,
              items: [
                { course_id: "COMPSCI 300", title: "Programming II" },
                { course_id: "COMPSCI 400", title: "Programming III" },
              ],
            },
            stats: { gpa: 3.4 },
          },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    await execute("get_department", { subject: "COMPSCI" });
    await execute("get_department_catalog", { subject: "compsci" });
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/departments/COMPSCI.json",
      "/departments/COMPSCI/catalog.json",
    ]);
  });
});

describe("WebMCP navigation tools", () => {
  it("opens catalog pages in the current tab", async () => {
    const navigate = vi.fn().mockResolvedValue(undefined);
    const tools = createWebmcpTools({ navigate });
    expect(await execute("open_course", { course: "COMPSCI 300" }, tools)).toBe(
      "Opened /courses/COMPSCI_300",
    );
    expect(await execute("open_instructor", { instructor: "ADA" }, tools)).toBe(
      "Opened /instructors/ADA",
    );
    expect(
      await execute("open_department", { subject: "compsci" }, tools),
    ).toBe("Opened /departments/COMPSCI");
    expect(await execute("open_explorer", { subject: "COMPSCI" }, tools)).toBe(
      "Opened /explorer/COMPSCI",
    );
    expect(
      await execute("open_search", { q: "java", kind: "course" }, tools),
    ).toBe("Opened /search?q=java&kind=course");
    expect(navigate.mock.calls.map((call) => call[0])).toEqual([
      "/courses/COMPSCI_300",
      "/instructors/ADA",
      "/departments/COMPSCI",
      "/explorer/COMPSCI",
      "/search?q=java&kind=course",
    ]);
  });
});

describe("WebMCP registration", () => {
  it.each([
    ["search_courses", { page: -1 }],
    ["search_courses", { term: "fall" }],
    ["search_courses", { kind: "instructor" }],
    ["get_course", { course: "../../api/status" }],
    ["get_course_grades", { course_uid: "../status" }],
    ["get_instructor", { instructor: "../status" }],
    ["get_department", { subject: "../status" }],
    ["open_explorer", { subject: "../status" }],
  ])("rejects invalid %s input before fetching", async (name, input) => {
    const fetch = vi.fn();
    const navigate = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      execute(
        name as string,
        input as Record<string, unknown>,
        createWebmcpTools({ navigate }),
      ),
    ).rejects.toThrow("Invalid tool input");
    expect(fetch).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
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

  it("registers every tool once and unregisters on disposal", async () => {
    const registerTool = vi.fn().mockResolvedValue(undefined);
    const dispose = registerCourseTools({
      registerTool,
    } as unknown as WebMCP.ModelContext);
    await vi.waitFor(() =>
      expect(registerTool).toHaveBeenCalledTimes(courseTools.length),
    );
    expect(registerTool.mock.calls.map((call) => call[0].name).sort()).toEqual([
      "get_course",
      "get_course_grades",
      "get_department",
      "get_department_catalog",
      "get_instructor",
      "get_instructor_courses",
      "get_instructor_history",
      "get_instructor_reviews",
      "list_departments",
      "open_course",
      "open_department",
      "open_explorer",
      "open_instructor",
      "open_search",
      "search_courses",
      "search_instructors",
    ]);
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
