import { describe, expect, it } from "vitest";
import { parseTranscript } from "./transcript";

describe("parseTranscript", () => {
  it("reads one turn per line, 'Speaker: text'", () => {
    const result = parseTranscript("Ana: Can you resend the invoice?\nBen: Sure, I'll do it: today.");
    expect(result).toEqual({
      ok: true,
      turns: [
        { speaker: "Ana", text: "Can you resend the invoice?" },
        { speaker: "Ben", text: "Sure, I'll do it: today." },
      ],
    });
  });

  it("ignores blank lines and surrounding space, and accepts Windows line endings", () => {
    const result = parseTranscript("\n  Ana :  Hello.  \r\n\r\nBen: Hi.\n");
    expect(result).toEqual({
      ok: true,
      turns: [
        { speaker: "Ana", text: "Hello." },
        { speaker: "Ben", text: "Hi." },
      ],
    });
  });

  it("names the first line that has no speaker", () => {
    expect(parseTranscript("Ana: Hello.\nhello there")).toEqual({
      ok: false,
      error: "Line 2 needs a speaker, like “Ana: Hello.”",
    });
  });

  it.each(["", "   \n \n"])("asks for some text when it is %p", (text) => {
    expect(parseTranscript(text)).toEqual({ ok: false, error: "Add a few lines of conversation first." });
  });

  it("rejects a speaker name over 100 characters and a line with no words after the colon", () => {
    expect(parseTranscript(`${"x".repeat(101)}: hi`).ok).toBe(false);
    expect(parseTranscript("Ana:   ")).toEqual({ ok: false, error: "Line 1 needs a speaker, like “Ana: Hello.”" });
  });

  it("stops at the API's limits on turns and length", () => {
    const tooMany = Array.from({ length: 201 }, () => "A: hi").join("\n");
    expect(parseTranscript(tooMany)).toEqual({ ok: false, error: "That is more than 200 turns; trim it down." });
    const tooLong = `A: ${"x".repeat(20_001)}`;
    expect(parseTranscript(tooLong)).toEqual({ ok: false, error: "That is over 20,000 characters; trim it down." });
  });
});
