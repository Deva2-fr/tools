import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, api, apiUploadProgress, downloadFile } from "../api";
import { useRefOptions } from "../components";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDate, TableWrap } from "../ui";

interface Analysis { title: string; summary: string; parties: string[]; amount: string; key_dates: { label: string; date: string }[]; notice: string; points_attention: string[] }

/** Analyse d'un contrat par l'IA : résumé, dates clés (transformables en rappels), préavis. */
function AnalysisModal({ file, onClose }: { file: Row; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["file-ai", file.id], queryFn: () => api<Analysis>(`/files/${file.id}/ai-analyze`, "POST"), staleTime: Infinity, retry: false });
  const [done, setDone] = useState<string[]>([]);
  const remind = useMutation({
    mutationFn: (d: { label: string; date: string }) => api("/crm/tasks", "POST", { title: `${d.label} – ${file.name}`, due_date: d.date, company_id: file.company_id ?? null, notes: "Créé depuis l'analyse IA du document." }),
    onSuccess: (_r, d) => { setDone((x) => [...x, d.date + d.label]); qc.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  const a = q.data;
  return (
    <Modal title={`✨ Analyse : ${file.name}`} onClose={onClose} wide>
      {q.isLoading ? <p className="flex items-center gap-2 py-6 text-sm text-slate-500"><span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />L'IA lit le document…</p> : q.error ? <ErrorMsg error={q.error} /> : a && (
        <div className="space-y-4 text-sm">
          <div><p className="font-serif text-lg text-slate-900">{a.title}</p><p className="mt-1 text-slate-600">{a.summary}</p></div>
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[140px_1fr]">
            {a.parties.length > 0 && <><dt className="text-slate-400">Parties</dt><dd>{a.parties.join(", ")}</dd></>}
            {a.amount && <><dt className="text-slate-400">Montant</dt><dd>{a.amount}</dd></>}
            {a.notice && <><dt className="text-slate-400">Préavis</dt><dd>{a.notice}</dd></>}
          </dl>
          {a.key_dates.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">Dates clés</p>
              <ul className="divide-y divide-slate-100 rounded border border-slate-200">
                {a.key_dates.map((d) => (
                  <li key={d.date + d.label} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                    <span><b>{fmtDate(d.date)}</b> · {d.label}</span>
                    {done.includes(d.date + d.label) ? <span className="text-xs text-emerald-700">✓ Rappel créé</span>
                      : <button className="text-xs font-medium text-brand-600 hover:underline" disabled={remind.isPending} onClick={() => remind.mutate(d)}>+ Créer un rappel</button>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {a.points_attention.length > 0 && <div><p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">Points d'attention</p><ul className="list-disc space-y-0.5 pl-5">{a.points_attention.map((p) => <li key={p}>{p}</li>)}</ul></div>}
          <ErrorMsg error={remind.error} />
          <p className="text-xs text-slate-400">Résumé généré par l'IA : vérifiez les dates importantes dans le document.</p>
        </div>
      )}
    </Modal>
  );
}

interface Folder { id: number; name: string; parent_id: number | null; files: number; folders: number }

/** Chemin « RH › Contrats » d'un dossier. */
function pathOf(folders: Folder[], id: number | null): Folder[] {
  const out: Folder[] = [];
  let cur = folders.find((f) => f.id === id);
  while (cur && out.length < 50) { out.unshift(cur); cur = folders.find((f) => f.id === cur!.parent_id); }
  return out;
}

/** Arborescence indentée, pour choisir un dossier de destination. */
function treeOptions(folders: Folder[], parent: number | null = null, depth = 0): [number, string][] {
  return folders.filter((f) => f.parent_id === parent).flatMap((f) => [[f.id, `${"\u00a0\u00a0\u00a0".repeat(depth)}📁 ${f.name}`] as [number, string], ...treeOptions(folders, f.id, depth + 1)]);
}

function FolderModal({ title, initial, onSave, onClose, busy, error }: { title: string; initial: string; onSave: (name: string) => void; onClose: () => void; busy: boolean; error: unknown }) {
  const [name, setName] = useState(initial);
  return (
    <Modal title={title} onClose={onClose}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSave(name.trim()); }}>
        <Field label="Nom du dossier"><input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Ex : Assurances" /></Field>
        <ErrorMsg error={error} />
        <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" busy={busy} disabled={!name.trim()}>Enregistrer</Button></div>
      </form>
    </Modal>
  );
}

const CATS: [string, string][] = [["legal", "Juridique (Kbis, statuts)"], ["contrat", "Contrat"], ["assurance", "Assurance"], ["facture", "Facture fournisseur"], ["rh", "RH"], ["projet", "Projet"], ["autre", "Autre"]];
const VIDEO = /\.(mp4|mov|m4v|webm)$/i;
const size = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} Mo` : `${Math.ceil(n / 1024)} Ko`);

export default function Documents() {
  const qc = useQueryClient();
  const companies = useRefOptions("/crm/companies", (r) => r.name);
  const names = Object.fromEntries(companies.map(([v, l]) => [v, l]));
  const [q, setQ] = useState("");
  const [cwd, setCwd] = useState<number | null>(null); // dossier ouvert (null = racine)
  const [folderEdit, setFolderEdit] = useState<"new" | Folder | null>(null);
  const [moving, setMoving] = useState<Row | null>(null);
  const [analyzing, setAnalyzing] = useState<Row | null>(null);
  const foldersQ = useQuery({ queryKey: ["file-folders"], queryFn: () => api<Folder[]>("/files/folders") });
  const folders = foldersQ.data ?? [];
  const crumbs = pathOf(folders, cwd);
  const here = folders.filter((f) => f.parent_id === cwd);
  const pathLabel = (id: number | null) => (id ? pathOf(folders, id).map((f) => f.name).join(" › ") : "Racine");
  const saveFolder = useMutation({
    mutationFn: (name: string) => folderEdit === "new" ? api("/files/folders", "POST", { name, parent_id: cwd }) : api(`/files/folders/${(folderEdit as Folder).id}`, "PUT", { name, parent_id: (folderEdit as Folder).parent_id }),
    onSuccess: () => { setFolderEdit(null); qc.invalidateQueries(); },
  });
  const delFolder = useMutation({ mutationFn: (id: number) => api(`/files/folders/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries() });
  const move = useMutation({ mutationFn: ([id, folder_id]: [number, number | null]) => api(`/files/${id}/folder`, "PUT", { folder_id }), onSuccess: () => { setMoving(null); qc.invalidateQueries(); } });
  const [f, setF] = useState({ name: "", category: "legal", company_id: "", expires_on: "", notes: "" });
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<{ i: number; n: number; pct: number } | null>(null);
  const [failed, setFailed] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [playing, setPlaying] = useState<Row | null>(null);
  const list = useQuery({ queryKey: ["files", q, cwd], queryFn: () => api<Row[]>(`/files?q=${encodeURIComponent(q)}${cwd ? `&folder_id=${cwd}` : ""}`) });
  // Les fichiers partent l'un après l'autre avec les mêmes réglages ; un refus n'arrête pas les suivants.
  const up = useMutation({
    mutationFn: async () => {
      const errors: string[] = [];
      for (const [i, file] of files.entries()) {
        setProgress({ i: i + 1, n: files.length, pct: 0 });
        const fd = new FormData();
        fd.append("file", file);
        if (cwd) fd.append("folder_id", String(cwd));
        for (const [k, v] of Object.entries(f)) if (v && !(k === "name" && files.length > 1)) fd.append(k, v);
        try { await apiUploadProgress("/files", fd, (pct) => setProgress({ i: i + 1, n: files.length, pct })); }
        catch (e) { errors.push(`${file.name} : ${e instanceof Error ? e.message : String(e)}`); }
      }
      return errors;
    },
    onSuccess: (errors) => { setFailed(errors); setFiles([]); setF({ ...f, name: "", notes: "" }); qc.invalidateQueries(); },
    onSettled: () => setProgress(null),
  });
  const pick = (list: FileList | null) => { if (list?.length) { setFiles(Array.from(list)); setFailed([]); } };
  const del = useMutation({ mutationFn: (id: number) => api(`/files/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries() });
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <PageHeader title="Documents" subtitle="Le coffre de l'entreprise : Kbis, statuts, contrats, assurances, vidéos… PDF, images, Word, Excel jusqu'à 25 Mo ; vidéos MP4, MOV, WEBM jusqu'à 500 Mo. Plusieurs fichiers à la fois." />
      <Card className="mb-6">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (files.length) up.mutate(); }}>
          <div className="lg:col-span-2">
            <span className="mb-1 block text-xs font-medium text-slate-700">Fichiers *</span>
              <label onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files); }}
                className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded border-2 border-dashed px-3 py-4 text-center text-sm transition ${dragging ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:border-brand-500"}`}>
                <input type="file" multiple className="sr-only" onChange={(e) => { pick(e.target.files); e.target.value = ""; }} />
                {files.length ? <span className="text-slate-700"><b>{files.length}</b> fichier(s) : {files.slice(0, 3).map((x) => x.name).join(", ")}{files.length > 3 && "…"} · {size(files.reduce((t, x) => t + x.size, 0))}</span>
                  : <span className="text-slate-500">Glissez vos fichiers ici ou <span className="font-medium text-brand-600">cliquez pour choisir</span> (plusieurs possibles)</span>}
              </label>
          </div>
          <Field label="Nom affiché" hint={files.length > 1 ? "Plusieurs fichiers : chacun garde son nom" : undefined}><input value={f.name} disabled={files.length > 1} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={files[0]?.name} /></Field>
          <Field label="Catégorie"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{CATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Société liée"><select value={f.company_id} onChange={(e) => setF({ ...f, company_id: e.target.value })}><option value="">—</option>{companies.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          <Field label="Date d'expiration" hint="Ex : fin de contrat, validité d'une attestation"><input type="date" value={f.expires_on} onChange={(e) => setF({ ...f, expires_on: e.target.value })} /></Field>
          <div className="lg:col-span-2"><Field label="Notes"><input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field></div>
          <div className="flex flex-col justify-end gap-1"><span className="text-xs text-slate-500">Dans : <b>{pathLabel(cwd)}</b></span><Button type="submit" busy={up.isPending} disabled={!files.length}>{files.length > 1 ? `Téléverser ${files.length} fichiers` : "Téléverser"}</Button></div>
        </form>
        {progress && (
          <div className="mt-3 text-xs text-slate-500">
            Envoi {progress.n > 1 && `${progress.i}/${progress.n} – `}{progress.pct} %
            <div className="mt-1 h-1.5 overflow-hidden rounded bg-slate-100"><div className="h-full bg-brand-600 transition-all" style={{ width: `${progress.pct}%` }} /></div>
          </div>
        )}
        {failed.length > 0 && <div className="mt-3 rounded bg-red-50 px-3 py-2 text-xs text-red-700"><p className="font-medium">{failed.length} fichier(s) non envoyé(s) :</p><ul className="mt-1 list-disc pl-4">{failed.map((m) => <li key={m}>{m}</li>)}</ul></div>}
        <ErrorMsg error={up.error} />
      </Card>
      <Card title="Fichiers" action={<div className="flex flex-wrap items-center gap-2"><div className="w-56"><input placeholder="Rechercher dans tous les dossiers…" value={q} onChange={(e) => setQ(e.target.value)} /></div><Button data-tour="docs-new-folder" variant="soft" onClick={() => { saveFolder.reset(); setFolderEdit("new"); }}>+ Dossier</Button></div>}>
        {!q && (
          <div data-tour="docs-folders" className="mb-3">
            <nav className="mb-3 flex flex-wrap items-center gap-1 text-sm" aria-label="Dossier ouvert">
              <button className={cwd === null ? "font-semibold text-slate-900" : "text-brand-600 hover:underline"} onClick={() => setCwd(null)}>Documents</button>
              {crumbs.map((c) => <span key={c.id} className="flex items-center gap-1"><span className="text-slate-300">›</span><button className={c.id === cwd ? "font-semibold text-slate-900" : "text-brand-600 hover:underline"} onClick={() => setCwd(c.id)}>{c.name}</button></span>)}
            </nav>
            {here.length > 0 && (
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {here.map((f) => (
                  <li key={f.id} className="group flex items-center justify-between gap-2 rounded border border-slate-200 bg-stone-50 px-3 py-2 hover:border-brand-500">
                    <button className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm" onClick={() => setCwd(f.id)}>
                      <span className="text-lg">📁</span><span className="min-w-0"><span className="block truncate font-medium text-slate-800">{f.name}</span><span className="block text-xs text-slate-400">{f.files + f.folders === 0 ? "vide" : [f.files && `${f.files} fichier(s)`, f.folders && `${f.folders} dossier(s)`].filter(Boolean).join(" · ")}</span></span>
                    </button>
                    <span className="flex shrink-0 gap-2 text-xs">
                      <button className="text-brand-600" onClick={() => { saveFolder.reset(); setFolderEdit(f); }}>Renommer</button>
                      {f.files + f.folders === 0 && <button className="text-red-500" onClick={() => confirm(`Supprimer le dossier « ${f.name} » ?`) && delFolder.mutate(f.id)}>Supprimer</button>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <ErrorMsg error={delFolder.error ?? move.error} />
        {list.isLoading ? <Loading /> : !list.data?.length ? (q ? <Empty>Aucun document ne correspond.</Empty> : !here.length && <Empty>{cwd ? "Dossier vide : téléversez un fichier ou créez un sous-dossier." : "Aucun document."}</Empty>) : (
          <TableWrap><table className="w-full min-w-[480px] text-sm"><tbody className="divide-y divide-slate-100">
            {list.data.map((r) => <tr key={r.id}>
              <td className="py-2.5 pr-3">{VIDEO.test(r.original_name) && <button className="mr-1.5 text-brand-600" title="Lire la vidéo" onClick={() => setPlaying(r)}>▶</button>}<button className="font-medium text-brand-600" onClick={() => downloadFile(`/files/${r.id}/download`, r.original_name)}> {r.name}</button><span className="block text-xs text-slate-400">{q && <>📁 {pathLabel(r.folder_id)} · </>}{r.original_name} · {size(r.size)}</span></td>
              <td className="pr-3"><Badge>{CATS.find(([k]) => k === r.category)?.[1] ?? r.category}</Badge></td><td className="pr-3 text-slate-500">{names[r.company_id] ?? ""}</td>
              <td className="pr-3">{r.expires_on && <Badge tone={r.expires_on < today ? "red" : "amber"}>Expire le {fmtDate(r.expires_on)}</Badge>}</td>
              <td className="whitespace-nowrap text-right text-xs">{/\.(pdf|png|jpe?g)$/i.test(r.original_name) && <button className="mr-3 font-medium text-brand-600" onClick={() => setAnalyzing(r)}>✨ Analyser</button>}<button className="mr-3 text-brand-600" onClick={() => setMoving(r)}>Déplacer</button><button className="text-red-500" onClick={() => confirm("Supprimer ce fichier ?") && del.mutate(r.id)}>Supprimer</button></td></tr>)}
          </tbody></table></TableWrap>
        )}
      </Card>
      {playing && (
        <Modal title={playing.name} onClose={() => setPlaying(null)}>
          <video className="w-full rounded bg-black" controls autoPlay preload="metadata" src={`/api/files/${playing.id}/view`}>Votre navigateur ne peut pas lire cette vidéo.</video>
          <p className="mt-2 text-xs text-slate-400">Si la vidéo ne se lit pas (certains formats iPhone), <button className="text-brand-600 underline" onClick={() => downloadFile(`/files/${playing.id}/download`, playing.original_name)}>téléchargez-la</button>.</p>
        </Modal>
      )}
      {analyzing && <AnalysisModal file={analyzing} onClose={() => setAnalyzing(null)} />}
      {folderEdit && <FolderModal title={folderEdit === "new" ? `Nouveau dossier dans « ${pathLabel(cwd)} »` : "Renommer le dossier"} initial={folderEdit === "new" ? "" : folderEdit.name}
        onSave={(n) => saveFolder.mutate(n)} onClose={() => setFolderEdit(null)} busy={saveFolder.isPending} error={saveFolder.error} />}
      {moving && (
        <Modal title={`Déplacer « ${moving.name} »`} onClose={() => setMoving(null)}>
          <ul className="max-h-80 space-y-1 overflow-y-auto text-sm">
            {([[null, "🏠 Racine (Documents)"], ...treeOptions(folders)] as [number | null, string][]).map(([id, label]) => (
              <li key={id ?? "root"}><button disabled={id === moving.folder_id || move.isPending} onClick={() => move.mutate([moving.id, id])}
                className="w-full rounded px-2 py-1.5 text-left hover:bg-brand-50 disabled:cursor-default disabled:font-semibold disabled:text-slate-400 disabled:hover:bg-transparent">{label}{id === moving.folder_id && " (actuel)"}</button></li>
            ))}
          </ul>
          <ErrorMsg error={move.error} />
        </Modal>
      )}
    </>
  );
}
