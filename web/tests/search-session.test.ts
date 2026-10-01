import { describe, expect, it, vi } from "vitest";
import { eq } from "drizzle-orm";
import {
  createSearchReadContext,
  searchRequestPlatform,
  sessionDriver,
} from "../../src/lib/server/search-session";
import { courses } from "../../src/lib/server/schema";

function fixture() {
  const statement = {
    bind: vi.fn().mockReturnThis(),
    raw: vi.fn(async () => [["course", "TEST 100"]]),
    all: vi.fn(),
    run: vi.fn(),
    first: vi.fn(),
  };
  const session: D1DatabaseSession = {
    prepare: vi.fn(() => statement),
    batch: vi.fn(),
    getBookmark: vi.fn(() => "bookmark"),
  };
  const db: D1Database = {
    prepare: vi.fn(() => statement),
    batch: vi.fn(),
    exec: vi.fn(),
    dump: vi.fn(),
    withSession: vi.fn(() => ({ ...session, prepare: vi.fn(() => statement) })),
  };
  return { db, session, statement };
}
describe("typed request sessions", () => {
  it("retains Drizzle column inference through the session facade", async () => {
    const { db, statement } = fixture();
    const context = createSearchReadContext(db, "session");
    const rows = await context.orm
      .select({ uid: courses.uid, code: courses.code })
      .from(courses)
      .where(eq(courses.uid, "course"));
    expect(rows).toEqual([{ uid: "course", code: "TEST 100" }]);
    expect(statement.bind).toHaveBeenCalledWith("course");
    expect(db.withSession).toHaveBeenCalledWith("first-primary");
    expect(db.prepare).not.toHaveBeenCalled();
  });
  it("creates separate request contexts without mutating shared bindings", () => {
    const { db } = fixture();
    const platform = {
      env: { DB: db, D1_READ_MODE: "session" },
    } as App.Platform;
    const first = searchRequestPlatform(platform);
    const second = searchRequestPlatform(platform);
    expect(first.readContext).not.toBe(second.readContext);
    expect(first.readContext!.client).not.toBe(second.readContext!.client);
    expect(platform.readContext).toBeUndefined();
    expect(first.env.DB).toBe(db);
    expect(db.withSession).toHaveBeenCalledTimes(2);
  });
  it("keeps primary mode as the default and rejects unsupported driver operations", async () => {
    const { db, session } = fixture();
    expect(createSearchReadContext(db).client).toBe(db);
    expect(db.withSession).not.toHaveBeenCalled();
    const driver = sessionDriver(session);
    await expect(driver.exec("SELECT 1")).rejects.toThrow("unavailable");
    await expect(driver.dump()).rejects.toThrow("unavailable");
    expect(() => driver.withSession()).toThrow("request boundary");
  });
});
