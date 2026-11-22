import { useState } from "react";
import { fakeClient, ok } from "@/lib/testExports";
import { type ApiClient } from "@/api/client";
import { ImportForm } from "./ImportForm";
import { ImportFindings } from "./ImportFindings";
import { checkImport, readRequest,importBatch } from "@/lib/evalImports";
import type { components } from "@/api/schema";

type ImportRequest = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];

function onEmptyImportReport():ImportReport{
  return {
    batch: "",
    source: "",
    provenance: "",
    imported_on: "",
    generation_prompt: "",
    imported: 0,
    rejections: [],
    date_disagreements: [],
    near_duplicates: []
  };
}

export function EvalImporter({client}:{client:ApiClient}) {
  
  const [ir, setIR] = useState<ImportReport>(onEmptyImportReport());
  const [importState, setImportState] = useState<"editing" | "checking"|"checked" | "importing" | "staged">("editing");

  async function onImportClick() {
    setImportState("importing");
    try {
      const response = await importBatch(client,{batch: ir.batch, source: ir.source, content: "", provenance: ir.provenance, today: "", generation_prompt: ir.generation_prompt});
      if (response.ok) {
        setImportState("staged");
      } else {
        setImportState("checked");
      }
    } catch (e) {
      console.error(e);
      setImportState("checked");
    }
  }

  async function  onCheckImportForm (file: File | null, options: {
  batch: string;
  provenance: string;
  generationPrompt: string;
  }): Promise<void>{
    setImportState("editing");
    let checked = false;
    try {
      setImportState("checking");
      if(!file) return;
      const read = await readRequest(file,options)
      if(!read || !read.ok || !read.job) return;

      const result = await checkImport(client,read.job);
      if(result.ok){
        setIR(result.job)
        checked = true;
      }else{
        checked = false;
      }
    }catch(e){
      console.error(e);
    }finally{
      if(!checked){
        setImportState("editing");
      }else{
        setImportState("checked");
      }
    }
  }

  return (
    <div>
      <h2>Evaluation Importer</h2>
      <ImportForm  onCheck={onCheckImportForm}/>
      <ImportFindings importReport={ir}/>
      {importState === "checked" && (
        <button onClick={onImportClick}>
          Import {ir.imported} items
        </button>
      )}
      {importState === "staged" && (
        <p role="status">uv run eval review --batch {ir.batch}</p>
      )}
    </div>
  );
}
