import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, Empty, Loading, PageHeader, StatusDot, fmtDate } from "../ui";

interface Dash {
  projects: { total: number; up: number; down: number; items: { id: number; name: string; url: string; status: string; latency_ms: number | null }[] };
  alerts_open: number;
  alerts: { id: number; title: string; severity: "info" | "warning" | "critical"; created_at: string }[];
  vulnerabilities_open: number;
  mails_to_reply: number;
  taxes_upcoming: { id: number; title: string; due_date: string; days_left: number; amount: number | null }[];
}

function Stat({ label, value, tone, to }: { label: string; value: number | string; tone: string; to: string }) {
  return (
    <Link to={to} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand-500">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-2 text-3xl font-bold ${tone}`}>{value}</p>
    </Link>
  );
}

export default function Dashboard() {
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dash>("/dashboard"), refetchInterval: 30_000 });
  if (isLoading || !data) return <Loading />;
  return (
    <>
      <PageHeader title="Tableau de bord" subtitle="Tout ce qui demande votre attention, en un coup d'œil." />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Sites en ligne" value={`${data.projects.up}/${data.projects.total}`} tone={data.projects.down ? "text-red-600" : "text-emerald-600"} to="/projets" />
        <Stat label="Alertes ouvertes" value={data.alerts_open} tone={data.alerts_open ? "text-amber-600" : "text-slate-900"} to="/alertes" />
        <Stat label="Failles à traiter" value={data.vulnerabilities_open} tone={data.vulnerabilities_open ? "text-red-600" : "text-slate-900"} to="/alertes" />
        <Stat label="Mails à répondre" value={data.mails_to_reply} tone={data.mails_to_reply ? "text-brand-600" : "text-slate-900"} to="/mails" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
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
            <Empty>Rien d'urgent dans les 45 prochains jours 🎉</Empty>
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
            <Empty>Aucune alerte ouverte. Tout est calme ✅</Empty>
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
