import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, User, api, isManager } from "../api";
import { useRefOptions } from "../components";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, PageHeader, cx, fmtDate, fmtMoney } from "../ui";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => today().slice(0, 8) + "01";

function Report() {
  const [start, setStart] = useState(monthStart());
  const [end, setEnd] = useState(today());
  const { data } = useQuery({ queryKey: ["time-report", start, end], queryFn: () => api<{ rows: Row[]; total_hours: number }>(`/time/report?start=${start}&end=${end}`) });
  return (
    <Card title="Rentabilité par client" action={<div className="flex items-center gap-2"><input type="date" className="!w-auto" value={start} onChange={(e) => setStart(e.target.value)} /><span>→</span><input type="date" className="!w-auto" value={end} onChange={(e) => setEnd(e.target.value)} /></div>}>
      {!data ? <Loading /> : !data.rows.length ? <Empty>Aucune donnée sur la période.</Empty> : (
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="border-b text-left text-xs uppercase text-slate-400"><th className="py-2">Client</th><th className="text-right">Heures</th><th className="text-right">Dont facturables</th><th className="text-right">Facturé HT</th><th className="text-right">Coût du temps</th><th className="text-right">Marge</th></tr></thead>
          <tbody className="divide-y divide-slate-100">{data.rows.map((r) => (
            <tr key={String(r.company_id)}><td className="py-2.5 font-medium">{r.company}</td><td className="text-right">{r.hours}</td><td className="text-right">{r.billable_hours}</td><td className="text-right">{fmtMoney(r.invoiced_ht)}</td><td className="text-right">{fmtMoney(r.cost)}</td>
              <td className={cx("text-right font-bold", r.margin < 0 ? "text-red-600" : "text-emerald-800")}>{fmtMoney(r.margin)}</td></tr>))}</tbody></table></div>
      )}
      <p className="mt-3 text-xs text-slate-400">Coût du temps = heures × coût journalier du collaborateur ÷ 7 (renseigné dans Équipe, retrouvé via son e-mail).</p>
    </Card>
  );
}

export default function Time({ user }: { user: User }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"mine" | "report">("mine");
  const companies = useRefOptions("/crm/companies", (r) => r.name);
  const names = Object.fromEntries(companies.map(([v, l]) => [v, l]));
  const [f, setF] = useState({ work_date: today(), hours: "" as number | "", company_id: null as number | null, description: "", billable: true, hourly_rate: "" as number | "" });
  const list = useQuery({ queryKey: ["time"], queryFn: () => api<Row[]>(`/time?start=${monthStart()}`) });
  const add = useMutation({
    mutationFn: () => api("/time", "POST", { ...f, hours: Number(f.hours), hourly_rate: f.hourly_rate === "" ? null : Number(f.hourly_rate) }),
    onSuccess: () => { setF({ ...f, hours: "", description: "" }); qc.invalidateQueries(); },
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/time/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries() });
  const total = (list.data ?? []).reduce((a, r) => a + r.hours, 0);
  return (
    <>
      <PageHeader title="Suivi du temps" subtitle="Notez le temps passé par client : le Hub en déduit votre rentabilité." />
      {isManager(user) && <div className="mb-4 flex gap-2">{([["mine", "Saisie du mois"], ["report", "Rentabilité"]] as const).map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={cx("rounded px-3 py-1.5 text-sm font-medium", tab === k ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200")}>{l}</button>)}</div>}
      {tab === "report" ? <Report /> : (
        <>
          <Card className="mb-6">
            <form className="grid gap-3 sm:grid-cols-[150px_100px_1fr_1fr_110px_auto]" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
              <Field label="Date"><input type="date" required value={f.work_date} onChange={(e) => setF({ ...f, work_date: e.target.value })} /></Field>
              <Field label="Heures"><input type="number" step="0.25" min="0.25" max="24" required value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value === "" ? "" : Number(e.target.value) })} /></Field>
              <Field label="Client"><select value={f.company_id ?? ""} onChange={(e) => setF({ ...f, company_id: e.target.value ? Number(e.target.value) : null })}><option value="">— Interne —</option>{companies.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
              <Field label="Travail effectué"><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
              <Field label="Taux horaire €"><input type="number" step="1" min="0" value={f.hourly_rate} onChange={(e) => setF({ ...f, hourly_rate: e.target.value === "" ? "" : Number(e.target.value) })} /></Field>
              <div className="flex items-end gap-2"><label className="flex items-center gap-1 pb-2 text-xs"><input type="checkbox" checked={f.billable} onChange={(e) => setF({ ...f, billable: e.target.checked })} />Facturable</label><Button type="submit" busy={add.isPending}>Ajouter</Button></div>
            </form>
            <ErrorMsg error={add.error} />
          </Card>
          <Card title={`Ce mois-ci : ${total} h`}>
            {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucune saisie ce mois-ci.</Empty> : (
              <table className="w-full text-sm"><tbody className="divide-y divide-slate-100">
                {list.data.map((r) => <tr key={r.id}><td className="py-2 pr-3 text-slate-400">{fmtDate(r.work_date)}</td>{isManager(user) && <td className="pr-3 text-xs text-slate-400">{r.user_email}</td>}<td className="pr-3 font-medium">{names[r.company_id] ?? "Interne"}</td><td className="pr-3">{r.description}</td><td className="pr-3">{!r.billable && <Badge>Non facturable</Badge>}</td><td className="text-right font-bold">{r.hours} h</td><td className="w-8 text-right"><button className="text-xs text-red-500" onClick={() => del.mutate(r.id)}>✕</button></td></tr>)}
              </tbody></table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
