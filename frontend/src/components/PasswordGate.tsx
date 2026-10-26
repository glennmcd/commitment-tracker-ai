"use client";

import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { ApiConfigError, getApiClient } from "@/api/client";
import { NETWORK } from "@/lib/jobs";
import { setSource, takeLinkParams } from "@/lib/link";
import { clearPassword, getPassword, PASSWORD_REJECTED, setPassword } from "@/lib/password";

type State = "starting" | "locked" | "open";

/** The Authorization header carries Latin-1 only; a password outside it could never be the right one. */
function fitsInHeader(value: string): boolean {
  return [...value].every((char) => (char.codePointAt(0) ?? 0) <= 0xff);
}

/**
 * Shows `children` only after the visitor enters the site password. The API's Lambda authorizer is what enforces it,
 * so this only collects the password, checks it with one cheap call and sends it with every later request
 * (src/api/client.ts). The password is kept for the tab only. If the API later refuses it (changed, say), the gate
 * closes again. `preview` shows above the form while the gate is locked (the landing page's evaluation results).
 */
export function PasswordGate({ children, preview }: { children: ReactNode; preview?: ReactNode }) {
  const [state, setState] = useState<State>("starting");
  const [value, setValue] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  // Decided after mount: the static page can't know what this tab has stored or what the URL carries. A password in
  // the URL (`?password=...`) wins over a stored one and goes through the same check as a typed one.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs once, on mount.
  useEffect(() => {
    const { password, source } = takeLinkParams();
    if (source) setSource(source);
    if (password !== null) {
      setState("locked");
      void attempt(password);
      return;
    }
    setState(getPassword() ? "open" : "locked");
  }, []);

  useEffect(() => {
    const closed = () => {
      setValue("");
      setNotice("The password was not accepted. Enter it again.");
      setState("locked");
    };
    window.addEventListener(PASSWORD_REJECTED, closed);
    return () => window.removeEventListener(PASSWORD_REJECTED, closed);
  }, []);

  async function unlock(event: FormEvent) {
    event.preventDefault();
    await attempt(value);
  }

  async function attempt(candidate: string) {
    if (candidate === "") {
      setNotice("Enter the password.");
      return;
    }
    if (!fitsInHeader(candidate)) {
      setNotice("That password is not right.");
      return;
    }
    setChecking(true);
    setNotice(null);
    setPassword(candidate);
    try {
      const { response } = await getApiClient().GET("/samples");
      if (response.ok) {
        setState("open");
        return;
      }
      clearPassword();
      setNotice(
        response.status === 401 || response.status === 403
          ? "That password is not right."
          : "The API could not check the password. Try again in a moment.",
      );
    } catch (error) {
      clearPassword();
      setNotice(error instanceof ApiConfigError ? error.message : NETWORK);
    } finally {
      setChecking(false);
    }
  }

  if (state === "starting") return null;
  if (state === "open") return <>{children}</>;

  return (
    <>
      {preview}
      <form className="panel gate" onSubmit={unlock}>
        <div className="field">
          <label htmlFor="site-password">Password</label>
          <p className="hint">This demo is private. Enter the password you were given.</p>
          <input
            id="site-password"
            type="password"
            autoComplete="current-password"
            value={value}
            disabled={checking}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>
        {notice && (
          <p className="problem" role="alert">
            {notice}
          </p>
        )}
        <div className="actions">
          <button type="submit" disabled={checking}>
            {checking ? "Checking…" : "Unlock"}
          </button>
        </div>
      </form>
    </>
  );
}
