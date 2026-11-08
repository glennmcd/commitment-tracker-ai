import { ImportForm } from "@/components/ImportForm";

// Dev-only preview of ImportForm: run `bun run dev` and open /dev/import-form/.
// A static export still writes this route, so it renders nothing in a production build.
export default function ImportFormPreview() {
  if (process.env.NODE_ENV === "production") {
    return null;
  }
  return (
    <main style={{ padding: "2rem" }}>
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />
    </main>
  );
}
