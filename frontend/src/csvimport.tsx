import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api";
import { Button, ErrorMsg, Modal } from "./ui";

/** Bouton « Importer un CSV » : choisir un fichier (ou coller le contenu) puis envoyer au serveur. */
export function CsvImportButton({ endpoint, extra, hint, label = "Importer un CSV" }: { endpoint: string; extra?: Record<string, unknown>; hint: string; label?: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const run = useMutation({
    mutationFn: () => api<{ created: number; errors: string[] }>(endpoint, "POST", { ...extra, csv: text }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <>
      <Button variant="ghost" onClick={() => { run.reset(); setOpen(true); }}>{label}</Button>
      {open && (
        <Modal title={label} onClose={() => setOpen(false)} wide>
          <div className="space-y-3 text-sm">
            <p className="text-slate-500">{hint}</p>
            <input type="file" accept=".csv,text/csv,text/plain" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); }} />
            <textarea rows={6} className="font-mono text-xs" placeholder="…ou collez le contenu ici" value={text} onChange={(e) => setText(e.target.value)} />
            <ErrorMsg error={run.error} />
            {run.data && (
              <div className="rounded-lg bg-emerald-50 p-3 text-emerald-800">
                ✅ {run.data.created} ligne(s) importée(s).
                {run.data.errors.length > 0 && <ul className="mt-2 list-disc pl-5 text-amber-700">{run.data.errors.map((e) => <li key={e}>{e}</li>)}</ul>}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setOpen(false)}>Fermer</Button>
              <Button busy={run.isPending} disabled={!text.trim()} onClick={() => run.mutate()}>Importer</Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
