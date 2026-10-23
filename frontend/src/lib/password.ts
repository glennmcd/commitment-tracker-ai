const KEY = "ct-site-password";

/** Dispatched on `window` when the API refuses the password, so the gate can ask for it again. */
export const PASSWORD_REJECTED = "ct:password-rejected";

// Kept in memory too, so a browser that blocks storage still works until the page is reloaded.
let remembered: string | null = null;

/** The password the visitor entered in this tab, or null. It lives in sessionStorage, so closing the tab forgets it. */
export function getPassword(): string | null {
  try {
    return window.sessionStorage.getItem(KEY) ?? remembered;
  } catch {
    return remembered;
  }
}

export function setPassword(value: string): void {
  remembered = value;
  try {
    window.sessionStorage.setItem(KEY, value);
  } catch {
    // Storage is blocked; the in-memory copy carries this page.
  }
}

export function clearPassword(): void {
  remembered = null;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing stored.
  }
}

export function passwordRejected(): void {
  window.dispatchEvent(new Event(PASSWORD_REJECTED));
}
