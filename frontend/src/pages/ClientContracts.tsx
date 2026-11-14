import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useRefOptions } from "../components";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, TableWrap, cx, fmtDate, fmtMoney } from "../ui";

interface Renewal { state: "planned" | "draft" | "qonto" | "accepted" | "refused" | "deleted"; prepare_on: string; days_left: number; urgent: boolean; quote: { id: number; number: string | null; total_ht: number; status: string } | null }
interface Contract {
  id: number; company_id: number; company: string; project_id: number | null; project: string; name: string; kind: string; kind_label: string;
  unit_price: number; quantity: number; vat_rate: number; period: string; renewal_date: string; notice_days: number; active: boolean; notes: string; renewal: Renewal;
}

const KINDS: [string, string][] = [["hosting", "Hébergement"], ["domain", "Nom de domaine"], ["maintenance", "Maintenance / TMA"], ["license", "Licence / logiciel"], ["other", "Autre"]];
const PERIODS: [string, string][] = [["yearly", "Annuel"], ["quarterly", "Trimestriel"], ["monthly", "Mensuel"]];
const PER: Record<string, string> = { yearly: "an", quarterly: "trimestre", monthly: "mois" };

/** État du renouvellement : devis à préparer, prêt (brouillon), dans Qonto, accepté… */
function RenewalState({ r }: { r: Renewal }) {
  const quote = r.quote && <Link className="text-xs font-medium text-brand-600 hover:underline" to={`/facturation/${r.quote.id}`}>Ouvrir</Link>;
  const badge = {
    planned: <Badge>Devis préparé le {fmtDate(r.prepare_on)}</Badge>,
    draft: <Badge tone="blue">Devis prêt (brouillon)</Badge>,
    qonto: <Badge tone="amber">Dans Qonto</Badge>,
    accepted: <Badge tone="green">Accepté</Badge>,
    refused: <Badge tone="red">Refusé</Badge>,
    deleted: <Badge tone="slate">Devis supprimé</Badge>,
  }[r.state];
  return <span className="flex flex-wrap items-center gap-2">{badge}{quote}{r.urgent && <Badge tone="red">J-{Math.max(r.days_left, 0)}</Badge>}</span>;
}

function ContractForm({ initial, companyId, onClose }: { initial: Partial<Contract> | null; companyId?: number; onClose: () => void }) {
  const qc = useQueryClient();
  const companies = useRefOptions("/crm/companies", (r) => r.name);
  const projects = useRefOptions("/projects", (r) => r.name);
  const [f, setF] = useState({
    company_id: initial?.company_id ?? companyId ?? 0, project_id: initial?.project_id ?? null as number | null, name: initial?.name ?? "", kind: initial?.kind ?? "hosting",
    unit_price: initial?.unit_price ?? ("" as number | ""), quantity: initial?.quantity ?? 1, vat_rate: initial?.vat_rate ?? 20, period: initial?.period ?? "yearly",
    renewal_date: initial?.renewal_date ?? "", notice_days: initial?.notice_days ?? 30, active: initial?.active ?? true, notes: initial?.notes ?? "",
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, unit_price: Number(f.unit_price) || 0 };
      return initial?.id ? api(`/client-contracts/${initial.id}`, "PUT", body) : api("/client-contracts", "POST", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["client-contracts"] }); onClose(); },
  });
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));
  return (
    <Modal title={initial?.id ? "Modifier le contrat" : "Nouveau contrat client"} onClose={onClose}>
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {!companyId && <div className="sm:col-span-2"><Field label="Client *"><select required value={f.company_id || ""} onChange={(e) => set("company_id", Number(e.target.value))}><option value="">—</option>{companies.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field></div>}
        <div className="sm:col-span-2"><Field label="Intitulé *" hint="Repris sur le devis, ex : Hébergement acme.fr"><input required maxLength={200} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field></div>
        <Field label="Type"><select value={f.kind} onChange={(e) => set("kind", e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Projet / site" hint="Facultatif"><select value={f.project_id ?? ""} onChange={(e) => set("project_id", e.target.value ? Number(e.target.value) : null)}><option value="">—</option>{projects.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
        <Field label="Prix HT par période (€) *"><input type="number" step="0.01" min="0" required value={f.unit_price} onChange={(e) => set("unit_price", e.target.value === "" ? "" : Number(e.target.value))} /></Field>
        <Field label="Périodicité"><select value={f.period} onChange={(e) => set("period", e.target.value)}>{PERIODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Quantité"><input type="number" step="0.01" min="0.01" value={f.quantity} onChange={(e) => set("quantity", Number(e.target.value) || 1)} /></Field>
        <Field label="TVA"><select value={f.vat_rate} onChange={(e) => set("vat_rate", Number(e.target.value))}>{[20, 10, 5.5, 2.1, 0].map((r) => <option key={r} value={r}>{r} %</option>)}</select></Field>
        <Field label="Prochain renouvellement *" hint="Début de la prochaine période"><input type="date" required value={f.renewal_date} onChange={(e) => set("renewal_date", e.target.value)} /></Field>
        <Field label="Préparer le devis … jours avant"><input type="number" min={0} max={365} value={f.notice_days} onChange={(e) => set("notice_days", Number(e.target.value) || 0)} /></Field>
        <label className="flex items-center gap-2 text-sm text-slate-700 sm:col-span-2"><input type="checkbox" className="h-4 w-4" checked={f.active} onChange={(e) => set("active", e.target.checked)} />Actif (décoché : contrat résilié, plus de devis)</label>
        <div className="sm:col-span-2"><Field label="Notes"><input value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><ErrorMsg error={save.error} /></div>
        <div className="flex justify-end gap-2 sm:col-span-2"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" busy={save.isPending}>Enregistrer</Button></div>
      </form>
    </Modal>
  );
}

/** Contrats refacturés aux clients et devis de renouvellement (tous, ou ceux d'un client). */
export function ClientContracts({ companyId }: { companyId?: number }) {
  const qc = useQueryClient();
  const [kind, setKind] = useState("");
  const [editing, setEditing] = useState<Partial<Contract> | null | undefined>(undefined);
  const q = useQuery({
    queryKey: ["client-contracts", companyId ?? "all", kind],
    queryFn: () => api<Contract[]>(`/client-contracts?${companyId ? `company_id=${companyId}&` : ""}${kind ? `kind=${kind}` : ""}`),
  });
  const [msg, setMsg] = useState("");
  const prepare = useMutation({
    mutationFn: () => api<{ created: { id: number; title: string; total_ht: number }[] }>(`/client-contracts/prepare${companyId ? `?company_id=${companyId}` : ""}`, "POST"),
    onSuccess: (r) => { setMsg(r.created.length ? `${r.created.length} devis préparé(s) en brouillon.` : "Tous les contrats ont déjà leur devis pour la prochaine échéance."); qc.invalidateQueries(); },
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/client-contracts/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries({ queryKey: ["client-contracts"] }) });
  const rows = q.data ?? [];
  const yearly = rows.filter((c) => c.active).reduce((t, c) => t + c.unit_price * c.quantity * ({ yearly: 1, quarterly: 4, monthly: 12 }[c.period] ?? 1), 0);
  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      {!companyId && <select className="!w-auto" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Tous les types</option>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}
      <Button variant="ghost" busy={prepare.isPending} onClick={() => prepare.mutate()} title="Prépare sans attendre le délai les devis manquants pour la prochaine échéance">Préparer le devis maintenant</Button>
      <Button variant="soft" onClick={() => setEditing(null)}>+ Contrat</Button>
    </div>
  );
  return (
    <Card title={companyId ? "Contrats & renouvellements" : "Contrats clients"} className={companyId ? "lg:col-span-2" : undefined} action={actions}>
      <p className="mb-3 text-xs text-slate-500">Ce que vous refacturez aux clients (hébergement, domaine, maintenance, licences). 30 jours avant chaque échéance (réglable), le Hub prépare tout seul le <b>devis de renouvellement en brouillon</b> (un par client) et vous alerte : relisez-le, puis envoyez-le vers Qonto.{rows.length > 0 && <> Total actif : <b>{fmtMoney(yearly)} HT / an</b>.</>}</p>
      {msg && <p className="mb-3 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{msg}</p>}
      <ErrorMsg error={prepare.error ?? del.error} />
      {q.isLoading ? <Loading /> : !rows.length ? <Empty>{companyId ? "Aucun contrat pour ce client." : "Aucun contrat client : ajoutez les hébergements, domaines et contrats de maintenance que vous refacturez."}</Empty> : (
        <TableWrap><table className="w-full min-w-[760px] text-sm">
          <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400">{!companyId && <th className="py-2">Client</th>}<th className={companyId ? "py-2" : ""}>Contrat</th><th className="text-right">Prix HT</th><th>Renouvellement</th><th>Devis</th><th /></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((c) => (
              <tr key={c.id} className={cx(!c.active && "opacity-40")}>
                {!companyId && <td className="py-2.5"><Link className="text-brand-600 hover:underline" to={`/crm/societes/${c.company_id}`}>{c.company}</Link></td>}
                <td className={companyId ? "py-2.5" : ""}><span className="font-medium">{c.name}</span><span className="block text-xs text-slate-400">{c.kind_label}{c.project && ` · ${c.project}`}</span></td>
                <td className="whitespace-nowrap text-right tabular-nums">{fmtMoney(c.unit_price * c.quantity)} / {PER[c.period]}</td>
                <td className="whitespace-nowrap">{fmtDate(c.renewal_date)}{!c.active && <span className="ml-1 text-xs">(résilié)</span>}</td>
                <td>{c.active ? <RenewalState r={c.renewal} /> : "—"}</td>
                <td className="whitespace-nowrap text-right text-xs"><button className="mr-3 text-brand-600" onClick={() => setEditing(c)}>Modifier</button><button className="text-red-600" onClick={() => confirm(`Supprimer le contrat « ${c.name} » ?`) && del.mutate(c.id)}>Supprimer</button></td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap>
      )}
      {editing !== undefined && <ContractForm initial={editing} companyId={companyId} onClose={() => setEditing(undefined)} />}
    </Card>
  );
}
