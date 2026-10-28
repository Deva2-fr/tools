import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ResourcePage } from "../components";
import { Badge, fmtDate, fmtMoney } from "../ui";

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

export default function Renewals() {
  const today = new Date().toISOString().slice(0, 10);
  return (
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
      ]}
    />
  );
}
