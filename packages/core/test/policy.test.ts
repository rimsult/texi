import { describe, expect, it } from "vitest";
import { allowedLangs, isLangAllowed, isLevel, LEVELS, neighbourLevels } from "../src";

describe("language policy", () => {
  it("allows Russian only for A1–A2", () => {
    expect(allowedLangs("A1")).toEqual(["ru", "en"]);
    expect(allowedLangs("A2")).toEqual(["ru", "en"]);
    for (const l of ["B1", "B2", "C1", "C2"] as const) {
      expect(allowedLangs(l)).toEqual(["en"]);
      expect(isLangAllowed(l, "ru")).toBe(false);
    }
  });
  it("computes ±1 neighbour packs", () => {
    expect(neighbourLevels("A1")).toEqual(["A1", "A2"]);
    expect(neighbourLevels("B2")).toEqual(["B1", "B2", "C1"]);
    expect(neighbourLevels("C2")).toEqual(["C1", "C2"]);
  });
  it("guards level strings", () => {
    expect(LEVELS.every(isLevel)).toBe(true);
    expect(isLevel("D1")).toBe(false);
  });
});
