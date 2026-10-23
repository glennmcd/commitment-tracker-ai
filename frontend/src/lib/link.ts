const PASSWORD_PARAM = "password";
const SOURCE_PARAM = "pwsource";
const SOURCE_KEY = "ct-link-source";

/** What a shared link carried: `?password=...` to unlock the site and `?pwsource=...` to say whose link it was. */
export interface LinkParams {
  password: string | null;
  source: string | null;
}

// Kept in memory too, so a browser that blocks storage still reports the source until the page is reloaded.
let remembered: string | null = null;

/**
 * Reads both parameters from the address bar and removes them from the URL (and the history entry) so the password
 * is not left behind to be bookmarked or copied. Other parameters stay.
 */
export function takeLinkParams(): LinkParams {
  const url = new URL(window.location.href);
  const password = url.searchParams.get(PASSWORD_PARAM);
  const source = url.searchParams.get(SOURCE_PARAM);
  if (password === null && source === null) return { password, source };
  url.searchParams.delete(PASSWORD_PARAM);
  url.searchParams.delete(SOURCE_PARAM);
  try {
    window.history.replaceState(window.history.state, "", url);
  } catch {
    // The URL could not be rewritten; the values are still used.
  }
  return { password, source };
}

/** The link label for this tab, sent as `X-Source` so the API can log which link a visit came from. */
export function getSource(): string | null {
  try {
    return window.sessionStorage.getItem(SOURCE_KEY) ?? remembered;
  } catch {
    return remembered;
  }
}

export function clearSource(): void {
  remembered = null;
  try {
    window.sessionStorage.removeItem(SOURCE_KEY);
  } catch {
    // Nothing stored.
  }
}

export function setSource(value: string): void {
  remembered = value;
  try {
    window.sessionStorage.setItem(SOURCE_KEY, value);
  } catch {
    // Storage is blocked; the in-memory copy carries this page.
  }
}
