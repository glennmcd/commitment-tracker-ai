import { describe, expect, it } from "bun:test";
import { parsePasswords, putCommand } from "./upload-passwords.mjs";

describe("parsePasswords", () => {
  it("takes one password per line, ignoring blank lines, comments and CRLF", () => {
    const text = "# people\r\nalpha\r\n\r\n  # indented comment\r\nbeta gamma\r\n";
    expect(parsePasswords(text)).toEqual(["alpha", "beta gamma"]);
  });

  it("keeps spaces inside a password but not around it", () => {
    expect(parsePasswords("  padded  \n")).toEqual(["padded"]);
  });

  it("drops repeats, keeping the first", () => {
    expect(parsePasswords("a\nb\na\n")).toEqual(["a", "b"]);
  });

  it("refuses a file with no passwords", () => {
    expect(() => parsePasswords("# nothing\n\n")).toThrow("no passwords");
  });

  it("refuses a password the Authorization header cannot carry, naming the line but not the value", () => {
    const attempt = () => parsePasswords("fine\npäss€\n");
    expect(attempt).toThrow("line 2");
    expect(attempt).not.toThrow("päss");
  });
});

describe("putCommand", () => {
  it("reads the value from a file, so it never appears in the command line", () => {
    const args = putCommand({ name: "/x/PW", file: "/tmp/in.json", profile: "p", region: "us-east-2" });
    expect(args).toEqual([
      "ssm",
      "put-parameter",
      "--cli-input-json",
      "file:///tmp/in.json",
      "--profile",
      "p",
      "--region",
      "us-east-2",
    ]);
    expect(args.join(" ")).not.toContain("/x/PW");
  });
});
