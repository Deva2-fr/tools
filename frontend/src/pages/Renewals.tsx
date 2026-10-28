import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Row, api } from "../api";
import { ResourcePage } from "../components";
import { Badge, Button, Empty, ErrorMsg, Loading, Modal, fmtDate, fmtMoney } from "../ui";
import { STATUS } from "./Billing";

const KINDS: [string, string][] = [["domain", "Nom de domaine"], ["hosting", "Hébergement"], ["saas", "Logiciel / SaaS"], ["insurance", "Assurance"], ["contract", "Contrat"], ["other", "Autre"]];
const PERIODS: [string, string][] = [["monthly", "Mensuel"], ["quarterly", "Trimestriel"], ["yearly", "Annuel"]];

function Summary() {
  const { data } = useQuery({ queryKey: ["subs-sum"], queryFn: () => api<{ annual_total: number; by_kind: Record<string, number>; count: number }>("/subscriptions-summary") });
  if (!data) return null;
  return (
    <div className="mb-6 grid gap-4 sm:grid-cols-4">
      <div className="rounded-md border border-slate-200 bg-white p-4"><p className="text-xs uppercase text-slate-400">Coût annuel HT</p><p className="mt-1 text-xl font-bold">{fmtMoney(data.annual_total)}</p><p className="text-xs text-slate-400">{data.count} abonnements actifs</p></div>
      {Object.entries(data.by_kind).slice(0, 3).map(([k, v]) => <div key={k} className="rounded-md border border-slate-200 bg-white p-4"><p className="text-xs uppercase text-slate-400">{KINDS.find(([x]) => x === k)?.[1]}</p><p className="mt-1 text-xl font-bold">{fmtMoney(v)}<span className="text-xs font-normal text-slate-400"> /an</span></p></div>)}
    </div>
  );
}

/** Lier un abonnement aux factures qui le concernent (factures Qonto ou du Hub). */
function InvoiceLinks({ sub, onClose }: { sub: Row; onClose: () => void }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const linked = useQuery({ queryKey: ["sub-invoices", sub.id], queryFn: () => api<Row[]>(`/subscriptions/${sub.id}/invoices`) });
  const all = useQuery({ queryKey: ["billing", "invoice", ""], queryFn: () => api<Row[]>("/billing?kind=invoice") });
  useEffect(() => { if (linked.data) setPicked(new Set(linked.data.map((d) => d.id))); }, [linked.data]);
  const save = useMutation({
    mutationFn: () => api(`/subscriptions/${sub.id}/invoices`, "PUT", { doc_ids: [...picked] }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["res", "/subscriptions"] }); qc.invalidateQueries({ queryKey: ["sub-invoices", sub.id] }); onClose(); },
  });
  const needle = q.trim().toLowerCase();
  const rows = (all.data ?? []).filter((d) => !needle || [d.number, d.title, d.company_name].some((x) => String(x ?? "").toLowerCase().includes(needle)));
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <Modal title={`Factures liées – ${sub.name}`} onClose={onClose} wide>
      <p className="mb-3 text-sm text-slate-500">Cochez les factures qui correspondent à cet abonnement (refacturation au client, par exemple).</p>
      <input className="mb-3" placeholder="Rechercher un n°, un client, un objet…" value={q} onChange={(e) => setQ(e.target.value)} />
      {all.isLoading || linked.isLoading ? <Loading /> : !rows.length ? <Empty>Aucune facture. Synchronisez Qonto depuis Devis & factures.</Empty> : (
        <div className="max-h-96 overflow-y-auto rounded border border-slate-200"><table className="w-full text-sm"><tbody className="divide-y divide-slate-100">
          {rows.map((d) => (
            <tr key={d.id} className="cursor-pointer hover:bg-slate-50" onClick={() => toggle(d.id)}>
              <td className="w-8 py-2 pl-3"><input type="checkbox" readOnly checked={picked.has(d.id)} /></td>
              <td className="py-2 font-medium">{d.number ?? "Brouillon"}</td><td>{d.company_name || "—"}</td><td>{fmtDate(d.issue_date)}</td>
              <td className="text-right">{fmtMoney(d.total_ttc)}</td><td className="pl-3 pr-3"><Badge tone={STATUS[d.status]?.[1]}>{STATUS[d.status]?.[0] ?? d.status}</Badge></td>
            </tr>))}
        </tbody></table></div>
      )}
      <ErrorMsg error={save.error} />
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Annuler</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Enregistrer ({picked.size})</Button></div>
    </Modal>
  );
}

function LinkedInvoices({ sub }: { sub: Row }) {
  const { data } = useQuery({ queryKey: ["sub-invoices", sub.id], queryFn: () => api<Row[]>(`/subscriptions/${sub.id}/invoices`), enabled: sub.invoice_count > 0 });
  if (!sub.invoice_count) return <span className="text-slate-400">—</span>;
  return <span className="flex flex-wrap gap-x-2">{(data ?? []).slice(0, 3).map((d) => <Link key={d.id} className="text-brand-600" to={`/facturation/${d.id}`}>{d.number ?? `#${d.id}`}</Link>)}{sub.invoice_count > 3 && <span className="text-slate-400">+{sub.invoice_count - 3}</span>}</span>;
}

export default function Renewals() {
  const today = new Date().toISOString().slice(0, 10);
  const [links, setLinks] = useState<Row | null>(null);
  return (
    <>
    <ResourcePage
      title="Abonnements, domaines & contrats"
      subtitle="Ne laissez plus expirer un nom de domaine, une assurance ou un abonnement : le Hub vous prévient avant chaque renouvellement."
      endpoint="/subscriptions" newLabel="Nouvel abonnement" exportName="abonnements" headerExtra={<Summary />}
      initial={{ kind: "saas", period: "yearly", notice_days: 30, auto_renew: true, active: true, cost: 0 }}
      empty="Ajoutez vos domaines (deva2.fr, formasyl.org…), hébergements, licences et assurances."
      fields={[
        { name: "name", label: "Nom", required: true, hint: "Ex : formasyl.org, Google Workspace, RC Pro" },
        { name: "kind", label: "Type", type: "select", options: KINDS },
        { name: "vendor", label: "Fournisseur", hint: "OVH, Google, AXA…" },
        { name: "cost", label: "Coût HT par période (€)", type: "number" },
        { name: "period", label: "Périodicité", type: "select", options: PERIODS },
        { name: "renewal_date", label: "Prochain renouvellement", type: "date" },
        { name: "notice_days", label: "M'alerter … jours avant", type: "number", step: "1" },
        { name: "auto_renew", label: "Reconduction automatique", type: "checkbox" },
        { name: "active", label: "Actif", type: "checkbox" },
        { name: "notes", label: "Notes", type: "textarea" },
      ]}
      rowClass={(r) => (r.active ? "" : "opacity-40")}
      columns={[
        { label: "Nom", render: (r) => <span className="font-medium">{r.name}</span> },
        { label: "Type", render: (r) => <Badge>{KINDS.find(([k]) => k === r.kind)?.[1]}</Badge> },
        { label: "Fournisseur", render: (r) => r.vendor || "—" },
        { label: "Coût HT", render: (r) => `${fmtMoney(r.cost)} / ${PERIODS.find(([k]) => k === r.period)?.[1].toLowerCase()}` },
        { label: "Renouvellement", render: (r) => r.renewal_date ? <span className="flex items-center gap-2">{fmtDate(r.renewal_date)}{r.renewal_date < today ? <Badge tone="red">Dépassé</Badge> : (new Date(r.renewal_date).getTime() - Date.now()) / 864e5 < (r.notice_days || 30) ? <Badge tone="amber">Bientôt</Badge> : null}</span> : "—" },
        { label: "Auto", render: (r) => (r.auto_renew ? "Oui" : <Badge tone="amber">Non</Badge>) },
        { label: "Factures", render: (r) => <LinkedInvoices sub={r} /> },
      ]}
      rowActions={(r) => <button className="text-brand-600" onClick={() => setLinks(r)}>Lier des factures</button>}
    />
    {links && <InvoiceLinks sub={links} onClose={() => setLinks(null)} />}
    </>
  );
}
