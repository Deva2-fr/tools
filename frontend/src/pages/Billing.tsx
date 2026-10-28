import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Row, api, downloadFile } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, PageHeader, cx, fmtDate, fmtDateTime, fmtMoney } from "../ui";

export const STATUS: Record<string, [string, "slate" | "blue" | "green" | "red" | "amber"]> = {
  draft: ["Brouillon", "slate"], sent: ["Émis", "blue"], accepted: ["Accepté", "green"], refused: ["Refusé", "red"], paid: ["Payée", "green"], cancelled: ["Annulée", "red"],
};
interface Sum { year: number; invoiced_ht: number; collected: number; outstanding: number; overdue: number; overdue_count: number; open_quotes_amount: number; open_quotes_count: number; monthly_ht: number[] }

function Bars({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  const months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
  return (
    <div className="flex h-24 items-end gap-1.5">
      {values.map((v, i) => (
        <div key={i} className="flex h-full flex-1 flex-col items-center justify-end gap-1" title={`${months[i]} : ${fmtMoney(v)}`}>
          <div className="w-full min-h-0 rounded-t bg-brand-500/80" style={{ height: `${Math.max((v / max) * 100, v > 0 ? 4 : 0)}%` }} />
          <span className="text-[10px] text-slate-400">{months[i]}</span>
        </div>
      ))}
    </div>
  );
}

export default function Billing() {
  const nav = useNavigate();
  const [tab, setTab] = useState("all");
  const [q, setQ] = useState("");
  const params = tab === "quote" ? "kind=quote" : tab === "invoice" ? "kind=invoice" : tab === "overdue" ? "status=overdue" : "";
  const list = useQuery({ queryKey: ["billing", tab, q], queryFn: () => api<Row[]>(`/billing?${params}&q=${encodeURIComponent(q)}`) });
  const sum = useQuery({ queryKey: ["billing-sum"], queryFn: () => api<Sum>("/billing/summary") });
  const qc = useQueryClient();
  const qonto = useQuery({ queryKey: ["billing-qonto"], queryFn: () => api<{ configured: boolean; last_synced_at: string | null }>("/billing/qonto") });
  const sync = useMutation({ mutationFn: () => api<{ invoices: number; quotes: number; created: number; warnings: string[] }>("/billing/qonto/sync", "POST"), onSuccess: () => qc.invalidateQueries() });
  const viaQonto = !!qonto.data?.configured;
  const s = sum.data;
  return (
    <>
      <PageHeader title="Devis & factures" subtitle={viaQonto ? "Vos devis et factures Qonto, importés automatiquement : CA, encaissements, retards et relances." : "Créez, émettez et suivez vos devis et factures. Numérotation continue automatique, PDF prêt à envoyer."}
        action={<div className="flex gap-2">
          <Button variant="ghost" onClick={() => downloadFile("/billing/export/csv", "devis-factures.csv")}>Export comptable (CSV)</Button>
          <Button variant="soft" onClick={() => nav("/facturation/nouveau?kind=quote")}>+ Devis</Button>
          {viaQonto ? <Button busy={sync.isPending} onClick={() => sync.mutate()}>Synchroniser Qonto</Button>
            : <Button onClick={() => nav("/facturation/nouveau?kind=invoice")}>+ Facture</Button>}</div>} />
      {qonto.data && (
        <p className="mb-4 text-sm text-slate-500">
          {viaQonto
            ? <>Qonto connecté{qonto.data.last_synced_at ? <> · dernière synchronisation {fmtDateTime(qonto.data.last_synced_at)}</> : " · pas encore synchronisé"} · factures et devis Qonto importés toutes les heures. Les devis peuvent aussi être préparés ici (avec l'IA) puis envoyés vers Qonto.</>
            : <>Vos devis et factures sont dans Qonto ? Renseignez la clé API dans <b>Paramètres → Intégrations → Banque Qonto</b> pour les importer automatiquement.</>}
          {sync.data && <span className="text-emerald-800"> · {sync.data.invoices} facture(s) et {sync.data.quotes} devis à jour.</span>}
          {sync.data?.warnings?.map((w) => <span key={w} className="block text-amber-700">{w}</span>)}
        </p>
      )}
      <div className="mb-4"><ErrorMsg error={sync.error} /></div>
      {s && (
        <div className="mb-6 grid gap-px overflow-hidden rounded-md border border-slate-300 bg-slate-300 lg:grid-cols-[1fr_1fr_1fr_1fr_1.5fr]">
          {([["Facturé " + s.year + " (HT)", fmtMoney(s.invoiced_ht), ""], ["Encaissé " + s.year, fmtMoney(s.collected), "text-emerald-800"], ["Reste à encaisser", fmtMoney(s.outstanding), s.outstanding ? "text-amber-700" : ""],
            [`En retard (${s.overdue_count})`, fmtMoney(s.overdue), s.overdue ? "text-red-700" : ""]] as const).map(([l, v, tone]) => (
            <div key={l} className="bg-white p-4"><p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{l}</p><p className={cx("mt-2 font-serif text-2xl", tone)}>{v}</p></div>
          ))}
          <div className="bg-white p-4"><p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">CA mensuel HT · {s.open_quotes_count} devis en attente ({fmtMoney(s.open_quotes_amount)})</p><Bars values={s.monthly_ht} /></div>
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {([["all", "Tous"], ["quote", "Devis"], ["invoice", "Factures"], ["overdue", "En retard"]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={cx("rounded px-3 py-1.5 text-sm font-medium", tab === k ? "bg-brand-600 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200")}>{l}</button>
        ))}
        <div className="ml-auto w-60"><input placeholder="N° ou objet…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>
      <Card>
        {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucun document.</Empty> : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Numéro</th><th>Type</th><th>Client</th><th>Date</th><th>Échéance</th><th className="text-right">Total TTC</th><th className="text-right">Reste</th><th className="pl-4">Statut</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {list.data.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <td className="py-2.5"><Link className="font-medium text-brand-600" to={`/facturation/${d.id}`}>{d.number ?? "Brouillon"}</Link>{d.provider === "qonto" && <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Qonto</span>}{d.title && <span className="block text-xs text-slate-400">{d.title}</span>}</td>
                  <td>{d.kind === "quote" ? "Devis" : "Facture"}</td><td>{d.company_name || "—"}</td><td>{fmtDate(d.issue_date)}</td><td>{fmtDate(d.due_date)}</td>
                  <td className="text-right font-medium">{fmtMoney(d.total_ttc)}</td><td className="text-right">{d.remaining ? fmtMoney(d.remaining) : "—"}</td>
                  <td className="pl-4">{d.is_overdue ? <Badge tone="red">En retard</Badge> : <Badge tone={STATUS[d.status]?.[1]}>{STATUS[d.status]?.[0] ?? d.status}</Badge>}</td>
                </tr>
              ))}
            </tbody></table></div>
        )}
      </Card>
    </>
  );
}
