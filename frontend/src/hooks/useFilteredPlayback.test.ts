import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useFilteredPlayback } from "./useFilteredPlayback";
import type { Section } from "@/lib/sectionIndex";

const section = (id: string, start: number, end: number): Section => ({
  id,
  title: id,
  level: 2,
  startBlockIdx: start,
  endBlockIdx: end,
  durationMs: 0,
  subsections: [],
});

const blocks = (n: number) => Array.from({ length: n }, (_, idx) => ({ idx, est_duration_ms: 1000 }));
const states = (n: number) => Array.from({ length: n }, () => "cached" as const);

function run(
  numBlocks: number,
  sections: Section[],
  expanded: string[],
  currentBlock = 0,
) {
  const { result } = renderHook(() =>
    useFilteredPlayback(blocks(numBlocks), sections, new Set(expanded), states(numBlocks), currentBlock),
  );
  return result.current;
}

describe("useFilteredPlayback", () => {
  it("keeps blocks outside any section visible (preamble before first heading)", () => {
    // Regression: doc with 65 blocks whose only heading started at block 60 —
    // the progress bar showed just that section's blocks.
    const result = run(65, [section("refs", 60, 64)], ["refs"]);
    expect(result.filteredBlockCount).toBe(65);
    expect(result.filteredDuration).toBe(65000);
  });

  it("hides uncovered preamble never, even when the only section is collapsed", () => {
    const result = run(65, [section("refs", 60, 64)], []);
    expect(result.filteredBlockCount).toBe(60);
    expect(result.visualToAbsolute(59)).toBe(59);
    expect(result.absoluteToVisual(60)).toBeNull();
  });

  it("hides only collapsed sections and maps indices across the gap", () => {
    const sections = [section("a", 2, 4), section("b", 5, 7), section("c", 8, 9)];
    const result = run(10, sections, ["a", "c"], 8);
    // Visible: preamble 0-1, section a 2-4, section c 8-9
    expect(result.filteredBlockCount).toBe(7);
    expect(result.visualToAbsolute(5)).toBe(8);
    expect(result.absoluteToVisual(8)).toBe(5);
    expect(result.visualCurrentBlock).toBe(5);
    expect(result.filteredElapsedMs).toBe(5000);
  });

  it("reports current block as hidden when inside a collapsed section", () => {
    const result = run(10, [section("a", 2, 4)], [], 3);
    expect(result.isCurrentBlockHidden).toBe(true);
    expect(result.visualCurrentBlock).toBeNull();
  });

  it("returns identity mapping when there are no sections", () => {
    const result = run(5, [], [], 2);
    expect(result.filteredBlockCount).toBe(5);
    expect(result.visualToAbsolute(3)).toBe(3);
    expect(result.filteredElapsedMs).toBe(2000);
  });
});
