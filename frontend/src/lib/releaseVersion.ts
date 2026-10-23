/**
 * The released version, read from release-please's manifest (`.release-please-manifest.json` at the repository root),
 * which is the one place the version is kept up to date. `next.config.ts` calls this at build time. A missing or
 * malformed manifest gives no version, and the footer then shows none, rather than failing the build.
 */
export function versionFromManifest(text: string): string | undefined {
  let manifest: unknown;
  try {
    manifest = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (typeof manifest !== "object" || manifest === null) return undefined;
  const version = (manifest as Record<string, unknown>)["."];
  return typeof version === "string" && version !== "" ? version : undefined;
}
