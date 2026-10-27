import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, api, apiUpload, downloadFile } from "../api";
import { useRefOptions } from "../components";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, PageHeader, fmtDate } from "../ui";

const CATS: [string, string][] = [["legal", "Juridique (Kbis, statuts)"], ["contrat", "Contrat"], ["assurance", "Assurance"], ["facture", "Facture fournisseur"], ["rh", "RH"], ["autre", "Autre"]];
const size = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} Mo` : `${Math.ceil(n / 1024)} Ko`);

export default function Documents() {
  const qc = useQueryClient();
  const companies = useRefOptions("/crm/companies", (r) => r.name);
  const names = Object.fromEntries(companies.map(([v, l]) => [v, l]));
  const [q, setQ] = useState("");
  const [f, setF] = useState({ name: "", category: "legal", company_id: "", expires_on: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);
  const list = useQuery({ queryKey: ["files", q], queryFn: () => api<Row[]>(`/files?q=${encodeURIComponent(q)}`) });
  const up = useMutation({
    mutationFn: () => { const fd = new FormData(); fd.append("file", file!); for (const [k, v] of Object.entries(f)) if (v) fd.append(k, v); return apiUpload("/files", fd); },
    onSuccess: () => { setFile(null); setF({ ...f, name: "", notes: "" }); qc.invalidateQueries(); },
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/files/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries() });
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <PageHeader title="Documents" subtitle="Le coffre de l'entreprise : Kbis, statuts, contrats, assurances… PDF, images, Word, Excel (15 Mo max)." />
      <Card className="mb-6">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (file) up.mutate(); }}>
          <div className="lg:col-span-2"><Field label="Fichier *"><input type="file" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field></div>
          <Field label="Nom affiché"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={file?.name} /></Field>
          <Field label="Catégorie"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{CATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Société liée"><select value={f.company_id} onChange={(e) => setF({ ...f, company_id: e.target.value })}><option value="">—</option>{companies.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          <Field label="Date d'expiration" hint="Ex : fin de contrat, validité d'une attestation"><input type="date" value={f.expires_on} onChange={(e) => setF({ ...f, expires_on: e.target.value })} /></Field>
          <div className="lg:col-span-2"><Field label="Notes"><input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field></div>
          <div className="flex items-end"><Button type="submit" busy={up.isPending} disabled={!file}>Téléverser</Button></div>
        </form>
        <ErrorMsg error={up.error} />
      </Card>
      <Card title="Fichiers" action={<div className="w-56"><input placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} /></div>}>
        {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucun document.</Empty> : (
          <table className="w-full text-sm"><tbody className="divide-y divide-slate-100">
            {list.data.map((r) => <tr key={r.id}>
              <td className="py-2.5 pr-3"><button className="font-medium text-brand-600" onClick={() => downloadFile(`/files/${r.id}/download`, r.original_name)}>📎 {r.name}</button><span className="block text-xs text-slate-400">{r.original_name} · {size(r.size)}</span></td>
              <td className="pr-3"><Badge>{CATS.find(([k]) => k === r.category)?.[1] ?? r.category}</Badge></td><td className="pr-3 text-slate-500">{names[r.company_id] ?? ""}</td>
              <td className="pr-3">{r.expires_on && <Badge tone={r.expires_on < today ? "red" : "amber"}>Expire le {fmtDate(r.expires_on)}</Badge>}</td>
              <td className="text-right"><button className="text-xs text-red-500" onClick={() => confirm("Supprimer ce fichier ?") && del.mutate(r.id)}>Supprimer</button></td></tr>)}
          </tbody></table>
        )}
      </Card>
    </>
  );
}
