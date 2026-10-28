import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Row, api } from "../api";
import { ResourcePage, useRefOptions } from "../components";
import { Badge, Button, Empty, ErrorMsg, Loading, Modal, cx, fmtDate, fmtMoney } from "../ui";
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

type Kind = "transactions" | "expenses" | "invoices";
interface Links { invoices: Row[]; transactions: Row[]; expenses: Row[]; spent_12m: number; annual_cost: number }
const TABS: { key: Kind; label: string; ids: string; source: string; empty: string }[] = [
  { key: "transactions", label: "Mouvements bancaires", ids: "transaction_ids", source: "/transactions?limit=2000", empty: "Aucun débit. Importez vos opérations (Trésorerie → Synchroniser Qonto)." },
  { key: "expenses", label: "Notes de frais", ids: "expense_ids", source: "/expenses", empty: "Aucune note de frais." },
  { key: "invoices", label: "Factures", ids: "invoice_ids", source: "/billing?kind=invoice", empty: "Aucune facture." },
];

/** Une ligne de dépense, quelle que soit sa source, sous une forme commune. */
function norm(kind: Kind, r: Row, accounts: Record<number, string>) {
  if (kind === "transactions") return { id: r.id, date: r.tx_date, label: r.label, detail: accounts[r.account_id] ?? "", amount: Math.abs(r.amount), status: null as null | string };
  if (kind === "expenses") return { id: r.id, date: r.expense_date, label: r.reason, detail: r.employee, amount: r.amount_ttc, status: null };
  return { id: r.id, date: r.issue_date, label: r.number ?? "Brouillon", detail: r.company_name, amount: r.total_ttc, status: r.status as string };
}

/** Rattacher à un abonnement toutes les dépenses qui le concernent. */
function ExpenseLinks({ sub, onClose }: { sub: Row; onClose: () => void }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Kind>("transactions");
  const [q, setQ] = useState(sub.vendor ?? "");
  const [picked, setPicked] = useState<Record<Kind, Set<number>>>({ transactions: new Set(), expenses: new Set(), invoices: new Set() });
  const linked = useQuery({ queryKey: ["sub-links", sub.id], queryFn: () => api<Links>(`/subscriptions/${sub.id}/links`) });
  const meta = TABS.find((t) => t.key === tab)!;
  const source = useQuery({ queryKey: ["sub-source", tab], queryFn: () => api<Row[]>(meta.source) });
  const accounts = useQuery({ queryKey: ["res", "/accounts", ""], queryFn: () => api<Row[]>("/accounts") });
  useEffect(() => {
    if (linked.data) setPicked({ transactions: new Set(linked.data.transactions.map((d) => d.id)), expenses: new Set(linked.data.expenses.map((d) => d.id)), invoices: new Set(linked.data.invoices.map((d) => d.id)) });
  }, [linked.data]);
  const save = useMutation({
    mutationFn: () => api(`/subscriptions/${sub.id}/links`, "PUT", Object.fromEntries(TABS.map((t) => [t.ids, [...picked[t.key]]]))),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["res", "/subscriptions"] }); qc.invalidateQueries({ queryKey: ["sub-links", sub.id] }); onClose(); },
  });
  const accNames = Object.fromEntries((accounts.data ?? []).map((a) => [a.id, a.name]));
  const needle = q.trim().toLowerCase();
  const rows = (source.data ?? [])
    .filter((r) => tab !== "transactions" || r.amount < 0)
    .map((r) => norm(tab, r, accNames))
    .filter((r) => picked[tab].has(r.id) || !needle || [r.label, r.detail].some((x) => String(x ?? "").toLowerCase().includes(needle)));
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p[tab]); if (n.has(id)) n.delete(id); else n.add(id); return { ...p, [tab]: n }; });
  const total = TABS.reduce((a, t) => a + picked[t.key].size, 0);
  return (
    <Modal title={`Dépenses liées – ${sub.name}`} onClose={onClose} wide>
      <p className="mb-3 text-sm text-slate-500">Cochez tout ce qui a été payé pour cet abonnement : prélèvements bancaires, notes de frais, factures.</p>
      <div className="mb-3 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} className={cx("rounded px-3 py-1.5 text-sm font-medium", tab === t.key ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200")}>
            {t.label}{picked[t.key].size > 0 && <span className="ml-1.5 opacity-80">({picked[t.key].size})</span>}
          </button>
        ))}
      </div>
      <div className="mb-3 flex gap-2">
        <input placeholder="Rechercher un libellé, un fournisseur, un client…" value={q} onChange={(e) => setQ(e.target.value)} />
        {q && <Button variant="ghost" className="shrink-0 whitespace-nowrap" onClick={() => setQ("")}>Tout afficher</Button>}
      </div>
      {source.isLoading || linked.isLoading ? <Loading /> : !rows.length ? <Empty>{needle ? `Rien ne correspond à « ${q} ».` : meta.empty}</Empty> : (
        <div className="max-h-96 overflow-y-auto rounded border border-slate-200"><table className="w-full text-sm"><tbody className="divide-y divide-slate-100">
          {rows.map((d) => (
            <tr key={d.id} className="cursor-pointer hover:bg-slate-50" onClick={() => toggle(d.id)}>
              <td className="w-8 py-2 pl-3"><input type="checkbox" readOnly checked={picked[tab].has(d.id)} /></td>
              <td className="py-2">{fmtDate(d.date)}</td><td className="font-medium">{d.label}</td><td className="text-slate-500">{d.detail || "—"}</td>
              <td className="text-right">{fmtMoney(d.amount)}</td>
              <td className="pl-3 pr-3">{d.status && <Badge tone={STATUS[d.status]?.[1]}>{STATUS[d.status]?.[0] ?? d.status}</Badge>}</td>
            </tr>))}
        </tbody></table></div>
      )}
      <ErrorMsg error={save.error} />
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Annuler</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Enregistrer ({total})</Button></div>
    </Modal>
  );
}

function Spent({ sub }: { sub: Row }) {
  if (!sub.link_count) return <span className="text-slate-400">—</span>;
  const planned = sub.cost * ({ monthly: 12, quarterly: 4, yearly: 1 } as Record<string, number>)[sub.period];
  // Comparaison indicative : le payé est TTC, le coût prévu HT (d'où la marge de 25 %).
  const over = planned > 0 && sub.spent_12m > planned * 1.25;
  return (
    <span title={`${sub.link_count} dépense(s) liée(s) · prévu : ${fmtMoney(planned)} HT / an`}>
      <b className={over ? "text-amber-700" : ""}>{fmtMoney(sub.spent_12m)}</b>
      <span className="text-xs text-slate-400"> · {sub.link_count}</span>
      {over && <Badge tone="amber">au-dessus du prévu</Badge>}
    </span>
  );
}

const userRef = { endpoint: "/users/directory", label: (r: Row) => r.name };

export default function Renewals() {
  const today = new Date().toISOString().slice(0, 10);
  const users = Object.fromEntries(useRefOptions(userRef.endpoint, userRef.label));
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
        { name: "user_id", label: "Responsable", type: "ref", ref: userRef, hint: "Utilisateur du Hub concerné (licence nominative, carte utilisée…)" },
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
        { label: "Responsable", render: (r) => (r.user_id ? users[r.user_id] ?? "—" : <span className="text-slate-400">—</span>) },
        { label: "Coût HT", render: (r) => `${fmtMoney(r.cost)} / ${PERIODS.find(([k]) => k === r.period)?.[1].toLowerCase()}` },
        { label: "Renouvellement", render: (r) => r.renewal_date ? <span className="flex items-center gap-2">{fmtDate(r.renewal_date)}{r.renewal_date < today ? <Badge tone="red">Dépassé</Badge> : (new Date(r.renewal_date).getTime() - Date.now()) / 864e5 < (r.notice_days || 30) ? <Badge tone="amber">Bientôt</Badge> : null}</span> : "—" },
        { label: "Auto", render: (r) => (r.auto_renew ? "Oui" : <Badge tone="amber">Non</Badge>) },
        { label: "Payé (12 mois)", render: (r) => <Spent sub={r} /> },
      ]}
      rowActions={(r) => <button className="text-brand-600" onClick={() => setLinks(r)}>Dépenses liées</button>}
    />
    {links && <ExpenseLinks sub={links} onClose={() => setLinks(null)} />}
    </>
  );
}
