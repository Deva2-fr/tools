import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Row, api, downloadFile } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, PageHeader, TableWrap, cx, fmtDate, fmtMoney } from "../ui";

interface Month { month: string; income: number; expense: number; net: number; income_last_year: number; expense_last_year: number }
interface Overview {
  series: Month[]; balance: number; current: Month; avg_net_3m: number; runway_months: number | null; uncategorized: number;
  vat: { since: string; collected: number; deductible: number; due: number };
}
interface Tx { id: number; date: string; label: string; amount: number; category: string; locked: boolean; vat_amount: number | null; attachments: number; operation_type: string; billing_doc_id: number | null; invoice: Doc | null }
interface Doc { id: number; number: string | null; title: string; total_ttc: number; issue_date: string; company?: string }
interface CatRow { category: string; months: Record<string, number>; total: number; average: number; budget: number | null; over_budget: boolean }

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const monthLabel = (k: string, year = false) => `${MONTHS[Number(k.slice(5)) - 1]}${year ? ` ${k.slice(0, 4)}` : ""}`;
// Deux séries (palette catégorielle validée : bleu = entrées, orange = sorties).
const IN = "#2a78d6", OUT = "#eb6834";

function Tile({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="bg-white p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className={cx("mt-2 font-serif text-2xl", tone ?? "text-slate-900")}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** Entrées et sorties par mois : barres groupées, survol = détail du mois (et l'an dernier). */
function CashChart({ series }: { series: Month[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...series.flatMap((s) => [s.income, s.expense]));
  const H = 180;
  const h = (v: number) => Math.max(v > 0 ? 2 : 0, Math.round((v / max) * H));
  const cur = hover !== null ? series[hover] : null;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-xs text-slate-600">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: IN }} />Entrées</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: OUT }} />Sorties</span>
        <span className="ml-auto text-slate-500">{cur ? <>
          <b className="text-slate-800">{monthLabel(cur.month, true)}</b> · entrées {fmtMoney(cur.income)} · sorties {fmtMoney(cur.expense)} · <b className="text-slate-800">résultat {fmtMoney(cur.net)}</b>
          <span className="block text-right text-slate-400">un an avant : entrées {fmtMoney(cur.income_last_year)} · sorties {fmtMoney(cur.expense_last_year)}</span>
        </> : "Survolez un mois pour le détail"}</span>
      </div>
      <div className="relative" role="img" aria-label="Entrées et sorties d'argent par mois">
        <div className="absolute inset-x-0 border-t border-slate-200" style={{ top: 0 }} />
        <div className="absolute inset-x-0 border-t border-slate-100" style={{ top: H / 2 }} />
        <div className="relative z-10 flex items-end gap-1" style={{ height: H }}>
          {series.map((s, i) => (
            <div key={s.month} className={cx("flex h-full flex-1 cursor-default items-end justify-center gap-[2px] rounded-sm px-0.5", hover === i && "bg-slate-50")}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={0}
              aria-label={`${monthLabel(s.month, true)} : entrées ${fmtMoney(s.income)}, sorties ${fmtMoney(s.expense)}`}>
              <div className="w-full max-w-[14px] rounded-t" style={{ height: h(s.income), background: IN }} />
              <div className="w-full max-w-[14px] rounded-t" style={{ height: h(s.expense), background: OUT }} />
            </div>
          ))}
        </div>
        <div className="flex gap-1 border-t border-slate-300 pt-1">
          {series.map((s) => <span key={s.month} className="flex-1 text-center text-[10px] text-slate-500">{monthLabel(s.month)}</span>)}
        </div>
      </div>
    </div>
  );
}

function OverviewTab() {
  const [months, setMonths] = useState(12);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["finance-overview", months], queryFn: () => api<Overview>(`/finance/overview?months=${months}`) });
  const classify = useMutation({ mutationFn: () => api("/finance/recategorize", "POST"), onSuccess: () => qc.invalidateQueries() });
  if (!q.data) return q.error ? <ErrorMsg error={q.error} /> : <Loading />;
  const o = q.data;
  return (
    <div className="space-y-6">
      {o.uncategorized > 0 && (
        <p className="flex flex-wrap items-center gap-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {o.uncategorized} mouvement(s) pas encore classé(s).
          <Button variant="soft" busy={classify.isPending} onClick={() => classify.mutate()}>Classer automatiquement</Button>
        </p>
      )}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-300 bg-slate-300 lg:grid-cols-4">
        <Tile label="Solde bancaire" value={fmtMoney(o.balance)} />
        <Tile label="Résultat du mois" value={fmtMoney(o.current.net)} tone={o.current.net < 0 ? "text-red-700" : "text-emerald-800"}
          hint={`entrées ${fmtMoney(o.current.income)} · sorties ${fmtMoney(o.current.expense)}`} />
        <Tile label="Trésorerie restante" value={o.runway_months === null ? "Positive" : `${o.runway_months.toLocaleString("fr-FR")} mois`}
          tone={o.runway_months !== null && o.runway_months < 6 ? "text-red-700" : undefined}
          hint={`moyenne des 3 derniers mois : ${fmtMoney(o.avg_net_3m)} / mois`} />
        <Tile label={o.vat.due < 0 ? "Crédit de TVA (estimation)" : "TVA à reverser (estimation)"} value={fmtMoney(Math.abs(o.vat.due))}
          hint={`trimestre depuis le ${fmtDate(o.vat.since)} : collectée ${fmtMoney(o.vat.collected)} – déductible ${fmtMoney(o.vat.deductible)}`} />
      </div>
      <Card title="Entrées et sorties" action={<select className="!w-auto" value={months} onChange={(e) => setMonths(Number(e.target.value))}>{[6, 12, 24].map((m) => <option key={m} value={m}>{m} mois</option>)}</select>}>
        <CashChart series={o.series} />
      </Card>
      <Card title="Détail par mois">
        <TableWrap><table className="w-full min-w-[560px] text-sm">
          <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Mois</th><th className="text-right">Entrées</th><th className="text-right">Sorties</th><th className="text-right">Résultat</th><th className="text-right">Résultat un an avant</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {[...o.series].reverse().map((s) => (
              <tr key={s.month}><td className="py-2">{monthLabel(s.month, true)}</td><td className="text-right">{fmtMoney(s.income)}</td><td className="text-right">{fmtMoney(s.expense)}</td>
                <td className={cx("text-right font-medium", s.net < 0 && "text-red-700")}>{fmtMoney(s.net)}</td>
                <td className="text-right text-slate-500">{fmtMoney(s.income_last_year - s.expense_last_year)}</td></tr>
            ))}
          </tbody>
        </table></TableWrap>
        <p className="mt-2 text-xs text-slate-400">Calculé sur les mouvements bancaires (hors virements entre vos comptes). La TVA est une estimation : la déclaration fait foi.</p>
      </Card>
    </div>
  );
}

function ExpensesTab() {
  const qc = useQueryClient();
  const [months, setMonths] = useState(6);
  const [filter, setFilter] = useState("__none");
  const [search, setSearch] = useState("");
  const [rule, setRule] = useState({ pattern: "", category: "" });
  const cats = useQuery({ queryKey: ["finance-cats", months], queryFn: () => api<{ categories: string[]; months: string[]; rows: CatRow[] }>(`/finance/categories?months=${months}`) });
  const txs = useQuery({
    queryKey: ["finance-txs", filter, search],
    queryFn: () => api<Tx[]>(`/finance/transactions?limit=200&q=${encodeURIComponent(search)}${filter === "__none" ? "" : filter === "__unc" ? "&uncategorized=true" : `&category=${encodeURIComponent(filter)}`}`),
  });
  const rules = useQuery({ queryKey: ["finance-rules"], queryFn: () => api<{ id: number; pattern: string; category: string }[]>("/finance/rules") });
  const inval = () => qc.invalidateQueries({ predicate: (x) => String(x.queryKey[0]).startsWith("finance") });
  const setCat = useMutation({ mutationFn: ({ id, category, pattern }: { id: number; category: string; pattern: string }) => api(`/finance/transactions/${id}/category`, "PUT", { category, pattern }), onSuccess: inval });
  const setBudget = useMutation({ mutationFn: (b: { category: string; monthly_amount: number | null }) => api("/finance/budgets", "PUT", b), onSuccess: inval });
  const addRule = useMutation({ mutationFn: () => api("/finance/rules", "POST", rule), onSuccess: () => { setRule({ pattern: "", category: "" }); inval(); } });
  const delRule = useMutation({ mutationFn: (id: number) => api(`/finance/rules/${id}`, "DELETE"), onSuccess: inval });
  const list = cats.data?.categories ?? [];
  const change = (t: Tx, category: string) => {
    const word = prompt(`Classer aussi automatiquement les mouvements semblables en « ${category} » ? Indiquez un mot du libellé (ex : « ${t.label.split(" ")[0]} »), ou laissez vide.`, "") ?? "";
    setCat.mutate({ id: t.id, category, pattern: word.trim() });
  };
  return (
    <div className="space-y-6">
      <Card title="Dépenses par catégorie" action={<select className="!w-auto" value={months} onChange={(e) => setMonths(Number(e.target.value))}>{[3, 6, 12].map((m) => <option key={m} value={m}>{m} mois</option>)}</select>}>
        {!cats.data ? <Loading /> : !cats.data.rows.length ? <Empty>Aucune dépense sur la période.</Empty> : (
          <TableWrap><table className="w-full min-w-[640px] text-sm">
            <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Catégorie</th>{cats.data.months.map((m) => <th key={m} className="text-right">{monthLabel(m)}</th>)}<th className="text-right">Moyenne</th><th className="text-right">Budget / mois</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {cats.data.rows.map((r) => (
                <tr key={r.category}>
                  <td className="py-2"><button className="text-left hover:text-brand-600" onClick={() => setFilter(r.category)}>{r.category}</button> {r.over_budget && <Badge tone="red">Budget dépassé</Badge>}</td>
                  {cats.data!.months.map((m) => <td key={m} className="text-right tabular-nums">{r.months[m] ? fmtMoney(r.months[m]) : <span className="text-slate-300">—</span>}</td>)}
                  <td className="text-right tabular-nums text-slate-500">{fmtMoney(r.average)}</td>
                  <td className="text-right"><input type="number" min="0" step="10" className="!w-28 text-right" defaultValue={r.budget ?? ""} placeholder="—" aria-label={`Budget mensuel ${r.category}`}
                    onBlur={(e) => { const v = e.target.value === "" ? null : Number(e.target.value); if (v !== r.budget) setBudget.mutate({ category: r.category, monthly_amount: v }); }} /></td>
                </tr>
              ))}
            </tbody>
          </table></TableWrap>
        )}
        <p className="mt-2 text-xs text-slate-400">Un budget dépassé déclenche une alerte (une fois par mois). Cliquez une catégorie pour voir ses mouvements.</p>
        <ErrorMsg error={setBudget.error} />
      </Card>
      <Card title="Mouvements" action={<div className="flex flex-wrap gap-2">
        <input className="!w-48" placeholder="Rechercher un libellé…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="!w-auto" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="__none">Tous</option><option value="__unc">Non classés</option>{list.map((c) => <option key={c}>{c}</option>)}</select>
      </div>}>
        <ErrorMsg error={setCat.error} />
        {!txs.data ? <Loading /> : !txs.data.length ? <Empty>Aucun mouvement.</Empty> : (
          <TableWrap><table className="w-full min-w-[640px] text-sm"><tbody className="divide-y divide-slate-100">
            {txs.data.map((t) => (
              <tr key={t.id}>
                <td className="py-2 pr-3 text-slate-500">{fmtDate(t.date)}</td>
                <td className="pr-3">{t.label}</td>
                <td className={cx("whitespace-nowrap pr-3 text-right tabular-nums", t.amount > 0 ? "text-emerald-800" : "text-slate-800")}>{fmtMoney(t.amount)}</td>
                <td className="w-56"><select value={t.category} onChange={(e) => change(t, e.target.value)} aria-label="Catégorie">{!t.category && <option value="">— à classer —</option>}{list.map((c) => <option key={c}>{c}</option>)}</select></td>
                <td className="pl-2 text-xs text-slate-400">{t.locked && "manuel"}</td>
              </tr>
            ))}
          </tbody></table></TableWrap>
        )}
      </Card>
      <Card title="Règles de classement">
        <p className="mb-3 text-xs text-slate-500">Un libellé qui contient le mot indiqué reçoit la catégorie. Vos règles passent avant les règles intégrées (OVH, Google, URSSAF…). Les choix faits à la main ne sont jamais écrasés.</p>
        <form className="mb-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); addRule.mutate(); }}>
          <input className="!w-56" required minLength={2} placeholder="Mot du libellé (ex : Free Pro)" value={rule.pattern} onChange={(e) => setRule({ ...rule, pattern: e.target.value })} />
          <select className="!w-64" required value={rule.category} onChange={(e) => setRule({ ...rule, category: e.target.value })}><option value="">Catégorie…</option>{list.map((c) => <option key={c}>{c}</option>)}</select>
          <Button type="submit" variant="soft" busy={addRule.isPending}>Ajouter la règle</Button>
        </form>
        <ErrorMsg error={addRule.error} />
        {!!rules.data?.length && <ul className="divide-y divide-slate-100 text-sm">{rules.data.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-1.5"><span>« {r.pattern} » → <b>{r.category}</b></span><button className="text-xs text-red-600" onClick={() => delRule.mutate(r.id)}>Supprimer</button></li>
        ))}</ul>}
      </Card>
    </div>
  );
}

interface ClientRow { company_id: number; company: string; invoiced_ht: number; collected: number; outstanding: number; hours: number; time_cost: number; margin: number; margin_pct: number | null; hourly_value: number | null }

function ClientsTab() {
  const [months, setMonths] = useState(12);
  const q = useQuery({ queryKey: ["finance-clients", months], queryFn: () => api<ClientRow[]>(`/finance/clients?months=${months}`) });
  return (
    <Card title="Rentabilité par client" action={<select className="!w-auto" value={months} onChange={(e) => setMonths(Number(e.target.value))}>{[3, 6, 12, 24].map((m) => <option key={m} value={m}>{m} derniers mois</option>)}</select>}>
      {!q.data ? <Loading /> : !q.data.length ? <Empty>Aucune facture ni temps saisi sur la période.</Empty> : (
        <TableWrap><table className="w-full min-w-[760px] text-sm">
          <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Client</th><th className="text-right">Facturé HT</th><th className="text-right">Encaissé</th><th className="text-right">Reste dû</th><th className="text-right">Heures</th><th className="text-right">Coût du temps</th><th className="text-right">Marge</th><th className="text-right">Valeur / heure</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {q.data.map((r) => (
              <tr key={r.company_id}>
                <td className="py-2"><Link className="text-brand-600 hover:underline" to={`/crm/societes/${r.company_id}`}>{r.company}</Link></td>
                <td className="text-right tabular-nums">{fmtMoney(r.invoiced_ht)}</td><td className="text-right tabular-nums">{fmtMoney(r.collected)}</td>
                <td className={cx("text-right tabular-nums", r.outstanding > 0 && "text-amber-700")}>{fmtMoney(r.outstanding)}</td>
                <td className="text-right tabular-nums">{r.hours.toLocaleString("fr-FR")} h</td><td className="text-right tabular-nums">{fmtMoney(r.time_cost)}</td>
                <td className={cx("text-right font-medium tabular-nums", r.margin < 0 ? "text-red-700" : "text-emerald-800")}>{fmtMoney(r.margin)}{r.margin_pct !== null && <span className="ml-1 text-xs font-normal text-slate-500">({r.margin_pct} %)</span>}</td>
                <td className="text-right tabular-nums text-slate-600">{r.hourly_value !== null ? fmtMoney(r.hourly_value) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table></TableWrap>
      )}
      <p className="mt-2 text-xs text-slate-400">Marge = facturé HT – coût du temps passé (coût journalier des collaborateurs ÷ 7 h, renseigné dans Équipe › Collaborateurs). Valeur / heure = facturé HT ÷ heures.</p>
    </Card>
  );
}

function ReceiptsTab() {
  const qc = useQueryClient();
  const now = new Date();
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const [month, setMonth] = useState(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}`);
  const receipts = useQuery({ queryKey: ["finance-receipts"], queryFn: () => api<Tx[]>("/finance/receipts?days=90") });
  const rec = useQuery({ queryKey: ["finance-rec"], queryFn: () => api<{ unmatched: (Tx & { suggestion: Doc | null })[]; matched: Tx[] }>("/finance/reconciliation") });
  const invoices = useQuery({ queryKey: ["finance-invoices"], queryFn: () => api<Row[]>("/billing?kind=invoice") });
  const match = useMutation({ mutationFn: ([id, doc]: [number, number | null]) => api(`/finance/transactions/${id}/match`, "PUT", { billing_doc_id: doc }), onSuccess: () => qc.invalidateQueries({ queryKey: ["finance-rec"] }) });
  const emitted = (invoices.data ?? []).filter((d) => d.kind === "invoice" && ["sent", "paid"].includes(d.status));
  const exportCsv = useMutation({
    mutationFn: () => {
      const [y, m] = month.split("-").map(Number);
      const last = new Date(y, m, 0).getDate();
      return downloadFile(`/finance/export.csv?start=${month}-01&end=${month}-${String(last).padStart(2, "0")}`, `mouvements-${month}.csv`);
    },
  });
  return (
    <div className="space-y-6">
      <Card title="Export pour l'expert-comptable">
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); exportCsv.mutate(); }}>
          <label className="text-sm"><span className="mb-1 block text-xs font-medium text-slate-700">Mois</span><input type="month" required value={month} onChange={(e) => setMonth(e.target.value)} /></label>
          <Button type="submit" busy={exportCsv.isPending}>Télécharger (CSV / Excel)</Button>
        </form>
        <p className="mt-2 text-xs text-slate-400">Date, libellé, montant, catégorie, TVA, justificatif présent ou non, facture rapprochée. Les justificatifs eux-mêmes restent dans Qonto.</p>
        <ErrorMsg error={exportCsv.error} />
      </Card>
      <Card title={`Justificatifs manquants${receipts.data ? ` (${receipts.data.length})` : ""}`} action={<a className="text-xs font-medium text-brand-600 hover:underline" href="https://app.qonto.com" target="_blank" rel="noreferrer noopener">Ajouter dans Qonto ↗</a>}>
        {!receipts.data ? <Loading /> : !receipts.data.length ? <Empty>Tous les paiements des 90 derniers jours ont leur justificatif. 🎉</Empty> : (
          <ul className="divide-y divide-slate-100 text-sm">{receipts.data.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-2"><span><span className="text-slate-500">{fmtDate(t.date)}</span> · {t.label} <span className="text-xs text-slate-400">{t.category}</span></span><b className="tabular-nums">{fmtMoney(t.amount)}</b></li>
          ))}</ul>
        )}
        <p className="mt-2 text-xs text-slate-400">Paiements par carte (et dépenses où Qonto demande un justificatif) sans pièce jointe ; impôts, salaires et frais bancaires exclus. La liste se met à jour à chaque synchronisation Qonto.</p>
      </Card>
      <Card title="Rapprochement des encaissements">
        <ErrorMsg error={match.error} />
        {!rec.data ? <Loading /> : !rec.data.unmatched.length ? <Empty>Tous les encaissements récents sont rapprochés d'une facture.</Empty> : (
          <ul className="divide-y divide-slate-100 text-sm">{rec.data.unmatched.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
              <span><span className="text-slate-500">{fmtDate(t.date)}</span> · {t.label} · <b className="text-emerald-800">{fmtMoney(t.amount)}</b></span>
              <span className="flex flex-wrap items-center gap-2">
                {t.suggestion && <Button variant="soft" busy={match.isPending} onClick={() => match.mutate([t.id, t.suggestion!.id])}>✓ {t.suggestion.number ?? `Facture n°${t.suggestion.id}`} · {t.suggestion.company}</Button>}
                <select className="!w-56" value="" onChange={(e) => e.target.value && match.mutate([t.id, Number(e.target.value)])} aria-label="Choisir la facture">
                  <option value="">{t.suggestion ? "Autre facture…" : "Choisir la facture…"}</option>
                  {emitted.map((d) => <option key={d.id} value={d.id}>{d.number ?? `n°${d.id}`} · {d.company_name} · {fmtMoney(d.total_ttc)}</option>)}
                </select>
              </span>
            </li>
          ))}</ul>
        )}
        {!!rec.data?.matched.length && <details className="mt-3 text-sm"><summary className="cursor-pointer text-slate-500">{rec.data.matched.length} encaissement(s) rapproché(s)</summary>
          <ul className="mt-2 divide-y divide-slate-100">{rec.data.matched.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-1.5"><span>{fmtDate(t.date)} · {t.label} → <b>{t.invoice?.number ?? `n°${t.billing_doc_id}`}</b></span><button className="text-xs text-red-600" onClick={() => match.mutate([t.id, null])}>Défaire</button></li>
          ))}</ul></details>}
        <p className="mt-2 text-xs text-slate-400">Le Hub propose la facture dont le montant correspond (le numéro ou le nom du client dans le libellé départagent). Les paiements restent gérés dans Qonto.</p>
      </Card>
    </div>
  );
}

const TABS = [["overview", "Vue d'ensemble"], ["expenses", "Où part l'argent"], ["clients", "Rentabilité par client"], ["receipts", "Justificatifs & export"]] as const;

export default function Finance() {
  const [tab, setTab] = useState<string>("overview");
  return (
    <>
      <PageHeader title="Finances" subtitle="Le suivi de l'argent, calculé à partir de vos mouvements Qonto et des factures synchronisées : rien n'est envoyé ni payé depuis le Hub." />
      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-slate-200 sm:gap-2">
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium sm:px-4 ${tab === k ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{label}</button>
        ))}
      </div>
      {tab === "overview" && <OverviewTab />}
      {tab === "expenses" && <ExpensesTab />}
      {tab === "clients" && <ClientsTab />}
      {tab === "receipts" && <ReceiptsTab />}
    </>
  );
}
