import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Row, api, apiUploadProgress, downloadFile } from "../../api";
import { Card, Empty, ErrorMsg, Loading, fmtDate } from "../../ui";

interface SubFolder { id: number; name: string }
interface ClientFolder { id: number; name: string; subfolders: SubFolder[] }

/** Documents du client sur sa fiche : ses sous-dossiers (01 Clients › <société> › …), ses fichiers et l'envoi direct. */
export function CompanyDocuments({ companyId }: { companyId: number }) {
  const qc = useQueryClient();
  const folder = useQuery({ queryKey: ["client-folder", companyId], queryFn: () => api<ClientFolder>(`/files/clients/${companyId}`) });
  const files = useQuery({ queryKey: ["files", "company", companyId], queryFn: () => api<Row[]>(`/files?company_id=${companyId}`) });
  const [target, setTarget] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState("");
  const [failed, setFailed] = useState<string[]>([]);
  const subs = folder.data?.subfolders ?? [];
  const dest = target ?? subs[0]?.id ?? folder.data?.id ?? null;
  const names = Object.fromEntries([...subs.map((s) => [s.id, s.name]), [folder.data?.id, "Dossier client"]]);

  // Envoi l'un après l'autre dans le sous-dossier choisi, fichiers liés à la société.
  const up = useMutation({
    mutationFn: async (list: File[]) => {
      const errors: string[] = [];
      for (const [i, file] of list.entries()) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("company_id", String(companyId));
        fd.append("category", "contrat");
        if (dest) fd.append("folder_id", String(dest));
        try { await apiUploadProgress("/files", fd, (pct) => setProgress(`Envoi ${list.length > 1 ? `${i + 1}/${list.length} – ` : ""}${pct} %`)); }
        catch (e) { errors.push(`${file.name} : ${e instanceof Error ? e.message : String(e)}`); }
      }
      return errors;
    },
    onSuccess: (errors) => { setFailed(errors); qc.invalidateQueries({ queryKey: ["files"] }); qc.invalidateQueries({ queryKey: ["file-folders"] }); },
    onSettled: () => setProgress(""),
  });
  const send = (list: FileList | null) => { if (list?.length) { setFailed([]); up.mutate(Array.from(list)); } };

  return (
    <Card title="Documents" className="lg:col-span-2" action={folder.data && <Link className="text-xs font-medium text-brand-600 hover:underline" to={`/documents?dossier=${folder.data.id}`}>Ouvrir dans Documents →</Link>}>
      {folder.isLoading ? <Loading /> : folder.error ? <ErrorMsg error={folder.error} /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Ranger dans">
            {subs.map((s) => (
              <button key={s.id} type="button" role="radio" aria-checked={dest === s.id} onClick={() => setTarget(s.id)}
                className={`rounded-full border px-2.5 py-1 text-xs ${dest === s.id ? "border-brand-600 bg-brand-50 font-medium text-brand-700" : "border-slate-200 text-slate-600 hover:border-brand-500"}`}>📁 {s.name}</button>
            ))}
          </div>
          <label onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); send(e.dataTransfer.files); }}
            className={`flex cursor-pointer items-center justify-center rounded border-2 border-dashed px-3 py-3 text-center text-sm transition ${dragging ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:border-brand-500"}`}>
            <input type="file" multiple className="sr-only" disabled={up.isPending} onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
            {progress ? <span className="text-slate-600">{progress}</span>
              : <span className="text-slate-500">Glissez des fichiers ici ou <span className="font-medium text-brand-600">cliquez</span> : rangés dans « {names[dest ?? 0] ?? "Dossier client"} »</span>}
          </label>
          {failed.length > 0 && <div className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{failed.map((m) => <p key={m}>{m}</p>)}</div>}
          {files.isLoading ? <Loading /> : !files.data?.length ? <Empty>Aucun document pour ce client.</Empty> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {files.data.map((f) => (
                <li key={f.id} className="flex items-center justify-between gap-3 py-2">
                  <button className="min-w-0 truncate text-left font-medium text-brand-600" onClick={() => downloadFile(`/files/${f.id}/download`, f.original_name)}>{f.name}</button>
                  <span className="shrink-0 text-xs text-slate-400">{names[f.folder_id] ? `📁 ${names[f.folder_id]} · ` : ""}{fmtDate(String(f.created_at).slice(0, 10))}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
