/** The page footer: the release version this build was made from, when the build knows it. */
export function Footer({ version }: { version: string | undefined }) {
  if (!version) return null;
  return (
    <footer className="site-footer">
      <p>Version {version}</p>
    </footer>
  );
}
