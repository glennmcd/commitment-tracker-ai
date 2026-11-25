import Link from "next/link";
import { type ApiClient, ApiConfigError, getApiClient } from "@/api/client";
import { EvalImporter } from "@/components/evalImports/EvalImporter";
import { PasswordGate } from "@/components/PasswordGate";

export default function EvalImportsPage() {
  

  return (
    <div>
      <h1>Import evaluation items.</h1>
      <p>Importing writes to the repository, so it works only against a local API.</p>
      <PasswordGate>
        <EvalImporter  />
      </PasswordGate>
    </div>
  );
}
