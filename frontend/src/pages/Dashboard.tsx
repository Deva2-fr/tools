import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { User, api } from "../api";
import { Badge, Card, Empty, Loading, PageHeader, StatusDot, fmtDate, fmtMoney } from "../ui";

interface Dash {
  projects: { total: number; up: number; down: number; items: { id: number; name: string; url: string; status: string; latency_ms: number | null }[] };
  alerts_open: number;
  alerts: { id: number; title: string; severity: "info" | "warning" | "critical"; created_at: string }[];
  vulnerabilities_open: number;
  mails_to_reply: number;
  tasks: { id: number; title: string; due_date: string | null; late: boolean }[];
  pipeline: { open_count: number; forecast: number };
  finance: null | { invoiced_ht: number; outstanding: number; overdue: number; balance: number; renewals: { id: number; name: string; date: string; cost: number }[] };
  taxes_upcoming: { id: number; title: string; due_date: string; days_left: number; amount: number | null }[];
}

function Stat({ label, value, tone, to }: { label: string; value: number | string; tone: string; to: string }) {
  return (
    <Link to={to} className="bg-white p-5 transition hover:bg-stone-50">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className={`mt-2 font-serif text-3xl ${tone}`}>{value}</p>
    </Link>
  );
}

export default function Dashboard({ user }: { user: User }) {
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dash>("/dashboard"), refetchInterval: 30_000 });
  if (isLoading || !data) return <Loading />;
  return (
    <>
      <PageHeader title="Tableau de bord" subtitle="Tout ce qui demande votre attention, en un coup d'œil." />
      <div data-tour="dash-tech" className="mb-6 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-300 bg-slate-300 lg:grid-cols-4">
        <Stat label="Sites en ligne" value={`${data.projects.up}/${data.projects.total}`} tone={data.projects.down ? "text-red-700" : "text-emerald-800"} to="/projets" />
        <Stat label="Alertes ouvertes" value={data.alerts_open} tone={data.alerts_open ? "text-amber-700" : "text-slate-900"} to="/alertes" />
        <Stat label="Failles à traiter" value={data.vulnerabilities_open} tone={data.vulnerabilities_open ? "text-red-700" : "text-slate-900"} to="/alertes" />
        <Stat label="Mails à répondre" value={data.mails_to_reply} tone={data.mails_to_reply ? "text-brand-600" : "text-slate-900"} to="/mails" />
      </div>
      {data.finance && (
        <div data-tour="dash-finance" className="mb-6 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-300 bg-slate-300 lg:grid-cols-4">
          <Stat label="Facturé cette année (HT)" value={fmtMoney(data.finance.invoiced_ht)} tone="text-slate-900" to="/facturation" />
          <Stat label="Reste à encaisser" value={fmtMoney(data.finance.outstanding)} tone={data.finance.overdue ? "text-red-700" : "text-amber-700"} to="/facturation" />
          <Stat label="Trésorerie" value={fmtMoney(data.finance.balance)} tone={data.finance.balance < 0 ? "text-red-700" : "text-emerald-800"} to="/tresorerie" />
          <Stat label="Pipeline pondéré" value={fmtMoney(data.pipeline.forecast)} tone="text-brand-600" to="/crm/pipeline" />
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Mes tâches" action={<Link to="/crm/taches" className="text-xs text-brand-600">Tout voir</Link>}>
          {data.tasks.length === 0 ? <Empty>Aucune tâche en attente </Empty> : (
            <ul className="divide-y divide-slate-100">
              {data.tasks.map((t) => (
                <li key={t.id} className="flex items-center justify-between py-2.5 text-sm"><span>{t.title}</span>{t.due_date && <Badge tone={t.late ? "red" : "slate"}>{fmtDate(t.due_date)}</Badge>}</li>
              ))}
            </ul>
          )}
        </Card>
        {data.finance ? (
          <Card title="Renouvellements à venir (30 j)" action={<Link to="/abonnements" className="text-xs text-brand-600">Tout voir</Link>}>
            {data.finance.renewals.length === 0 ? <Empty>Aucun renouvellement proche.</Empty> : (
              <ul className="divide-y divide-slate-100">
                {data.finance.renewals.map((r) => <li key={r.id} className="flex items-center justify-between py-2.5 text-sm"><span>{r.name}</span><span className="text-slate-500">{fmtDate(r.date)} · {fmtMoney(r.cost)}</span></li>)}
              </ul>
            )}
          </Card>
        ) : <Card title="Bienvenue"><p className="text-sm text-slate-500">Bonjour {user.name || user.email}  Retrouvez vos tâches, vos contacts et vos mails à répondre depuis le menu.</p></Card>}
        <Card title="Mes sites">
          {data.projects.items.length === 0 ? (
            <Empty>Aucun projet. <Link to="/projets" className="text-brand-600 underline">Ajoutez-en un</Link>.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.projects.items.map((p) => (
                <li key={p.id} className="flex items-center justify-between py-2.5">
                  <Link to={`/projets/${p.id}`} className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-900">{p.name}</p>
                    <p className="truncate text-xs text-slate-400">{p.url}</p>
                  </Link>
                  <div className="text-right">
                    <StatusDot status={p.status} />
                    {p.latency_ms != null && <p className="text-xs text-slate-400">{p.latency_ms} ms</p>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Prochaines échéances" action={<Link to="/impots" className="text-xs text-brand-600">Tout voir</Link>}>
          {data.taxes_upcoming.length === 0 ? (
            <Empty>Rien d'urgent dans les 45 prochains jours </Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.taxes_upcoming.map((t) => (
                <li key={t.id} className="flex items-center justify-between py-2.5 text-sm">
                  <span>{t.title}<span className="block text-xs text-slate-400">{fmtDate(t.due_date)}</span></span>
                  <Badge tone={t.days_left < 0 ? "red" : t.days_left <= 7 ? "amber" : "slate"}>
                    {t.days_left < 0 ? `En retard (${-t.days_left} j)` : t.days_left === 0 ? "Aujourd'hui" : `J-${t.days_left}`}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Dernières alertes" className="lg:col-span-2" action={<Link to="/alertes" className="text-xs text-brand-600">Tout voir</Link>}>
          {data.alerts.length === 0 ? (
            <Empty>Aucune alerte ouverte. Tout est calme </Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.alerts.map((a) => (
                <li key={a.id} className="flex items-center justify-between py-2.5 text-sm">
                  <span>{a.title}</span>
                  <Badge tone={a.severity === "critical" ? "red" : a.severity === "warning" ? "amber" : "blue"}>{a.severity === "critical" ? "Critique" : a.severity === "warning" ? "Attention" : "Info"}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
