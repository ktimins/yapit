import { describe, it, expect } from "vitest";
import { isSpeakable } from "./speakable";

describe("isSpeakable", () => {
  it("accepts words in any script and bare numbers", () => {
    expect(isSpeakable("Women and gendered violence")).toBe(true);
    expect(isSpeakable("日本語のテキスト")).toBe(true);
    expect(isSpeakable("2017")).toBe(true);
    expect(isSpeakable("privi-")).toBe(true);
  });

  it("rejects symbol-only blocks", () => {
    expect(isSpeakable("")).toBe(false);
    expect(isSpeakable("   ")).toBe(false);
    expect(isSpeakable("© ; & — ...")).toBe(false);
    expect(isSpeakable("★★★★★")).toBe(false);
    expect(isSpeakable("🎉🎉")).toBe(false);
  });
});
