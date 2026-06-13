import { describe, it, expect } from "vitest";
import { extractRunId, stripMarker } from "../../lib/gaa/marker";

describe("marker", () => {
  it("extracts the run id", () => {
    expect(extractRunId("Here it is.\n\n[[gaa:run_id=2026-06-13-revenue-drop-x-8a3c]]"))
      .toBe("2026-06-13-revenue-drop-x-8a3c");
    expect(extractRunId("no marker here")).toBeNull();
  });
  it("strips the marker from the visible text", () => {
    expect(stripMarker("Answer.\n\n[[gaa:run_id=abc]]")).toBe("Answer.");
    expect(stripMarker("clean")).toBe("clean");
  });
});
