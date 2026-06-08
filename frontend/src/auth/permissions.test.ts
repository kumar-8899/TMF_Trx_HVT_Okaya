import { describe, expect, it } from "vitest";

import { hasPermission } from "./permissions";

describe("hasPermission (mirrors backend)", () => {
  it.each([
    [["AUTH.MANAGE_USERS"], "AUTH.MANAGE_USERS", true],
    [["AUTH.*"], "AUTH.MANAGE_USERS", true],
    [["*"], "TEST.RUN", true],
    [["TEST.RUN"], "AUTH.MANAGE_USERS", false],
    [["AUTH.*"], "TEST.RUN", false],
    [[], "TEST.RUN", false],
  ] as [string[], string, boolean][])("perms=%j needs=%s -> %s", (perms, needed, ok) => {
    expect(hasPermission(perms, needed)).toBe(ok);
  });

  it("undefined perms -> false", () => {
    expect(hasPermission(undefined, "X.Y")).toBe(false);
  });
});
