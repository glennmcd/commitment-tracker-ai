// Uploads the site passwords to SSM, where the API's Lambda authorizer reads them (infra/lambda/authorizer).
//
//   bun scripts/upload-passwords.mjs passwords.txt [--profile g26work2] [--dry-run]
//
// The file holds one password per line; blank lines and lines starting with # are ignored. They are stored as one
// SecureString, one per line, replacing the previous value. API Gateway caches each authorizer answer for five
// minutes, so a removed password can keep working for up to that long.
//
// Passwords are never printed or put on a command line: the value goes to the AWS CLI through a private temp file that
// is removed afterwards. Keep the passwords file out of git (name it passwords.txt or put it outside the repo).
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { PASSWORD_PARAMETER, REGION } from "../infra/lib/config.ts";

const DEFAULT_PROFILE = "g26work2";

/** The Authorization header carries Latin-1 only (the page enforces the same), so anything else could never match. */
function fitsInHeader(value) {
  return [...value].every((char) => (char.codePointAt(0) ?? 0) <= 0xff);
}

/** The passwords in `text`: trimmed, without blanks, comments or repeats. Errors name a line, never its content. */
export function parsePasswords(text) {
  const found = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) return;
    if (!fitsInHeader(line)) {
      throw new Error(`line ${index + 1} has a character outside Latin-1, which the Authorization header cannot carry`);
    }
    if (!found.includes(line)) found.push(line);
  });
  if (found.length === 0) throw new Error("the file has no passwords");
  return found;
}

/** The `aws` arguments that store the parameter described by the JSON file; the value stays out of the arguments. */
export function putCommand({ file, profile, region }) {
  return ["ssm", "put-parameter", "--cli-input-json", `file://${file}`, "--profile", profile, "--region", region];
}

function main(argv) {
  const positional = argv.filter((arg) => !arg.startsWith("--"));
  const profileIndex = argv.indexOf("--profile");
  const profile = profileIndex >= 0 ? argv[profileIndex + 1] : DEFAULT_PROFILE;
  const dryRun = argv.includes("--dry-run");
  const source = positional.find((arg) => arg !== profile);
  if (!source || !profile) {
    console.error("usage: bun scripts/upload-passwords.mjs <passwords-file> [--profile <name>] [--dry-run]");
    return 2;
  }

  let passwords;
  try {
    passwords = parsePasswords(readFileSync(source, "utf8"));
  } catch (error) {
    console.error(`${source}: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
  const count = `${passwords.length} password${passwords.length === 1 ? "" : "s"}`;
  if (dryRun) {
    console.log(`Dry run: would store ${count} in ${PASSWORD_PARAMETER} (${REGION}, profile ${profile}).`);
    return 0;
  }

  const directory = mkdtempSync(path.join(tmpdir(), "ct-passwords-"));
  const file = path.join(directory, "put-parameter.json");
  try {
    writeFileSync(
      file,
      JSON.stringify({
        Name: PASSWORD_PARAMETER,
        Value: passwords.join("\n"),
        Type: "SecureString",
        Overwrite: true,
      }),
      { mode: 0o600 },
    );
    const result = spawnSync("aws", putCommand({ file, profile, region: REGION }), {
      stdio: ["ignore", "ignore", "inherit"],
    });
    if (result.error || result.status !== 0) {
      console.error(result.error ? `could not run aws: ${result.error.message}` : "aws ssm put-parameter failed.");
      return 1;
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
  console.log(`Stored ${count} in ${PASSWORD_PARAMETER}. The authorizer may take up to 5 minutes to see changes.`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main(process.argv.slice(2)));
}
