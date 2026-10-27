import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, api } from "../api";
import { FormModal, defaults } from "../components";
import { CsvImportButton } from "../csvimport";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, PageHeader, cx, fmtDate, fmtMoney } from "../ui";

interface Forecast { balance: number; lowest: number; end_balance: number; series: { date: string; balance: number }[]; events: { date: string; label: string; amount: number; type: string }[] }
const accountFields = [{ name: "name", label: "Nom du compte", required: true }, { name: "initial_balance", label: "Solde initial (€)", type: "number" as const, hint: "Le solde du compte à la date de départ de votre saisie" }, { name: "iban", label: "IBAN" }];
const txFields = (accounts: Row[]) => [
  { name: "account_id", label: "Compte", type: "select" as const, options: accounts.map((a) => [a.id, a.name] as [number, string]) },
  { name: "tx_date", label: "Date", type: "date" as const, required: true },
  { name: "label", label: "Libellé", required: true, wide: true },
  { name: "amount", label: "Montant (€)", type: "number" as const, required: true, hint: "Positif = encaissement, négatif = dépense" },
  { name: "category", label: "Catégorie" },
];
const TYPE: Record<string, string> = { invoice: "Facture à encaisser", tax: "Impôt / TVA", subscription: "Abonnement" };

function Chart({ series }: { series: Forecast["series"] }) {
  const vals = series.map((s) => s.balance);
  const min = Math.min(...vals, 0), max = Math.max(...vals, 1), span = max - min || 1;
  const pts = series.map((s, i) => `${(i / (series.length - 1)) * 100},${48 - ((s.balance - min) / span) * 44}`).join(" ");
  const zeroY = 48 - ((0 - min) / span) * 44;
  return (
    <div>
      <svg viewBox="0 0 100 52" preserveAspectRatio="none" className="h-40 w-full">
        <line x1="0" x2="100" y1={zeroY} y2={zeroY} stroke="#fca5a5" strokeDasharray="2 2" strokeWidth="0.4" vectorEffect="non-scaling-stroke" />
        <polyline points={pts} fill="none" stroke="#1f5f4f" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-xs text-slate-400"><span>{fmtDate(series[0].date)}</span><span>{fmtDate(series[series.length - 1].date)}</span></div>
    </div>
  );
}

export default function Treasury() {
  const qc = useQueryClient();
  const [days, setDays] = useState(90);
  const [acc, setAcc] = useState<number | "">("");
  const [modal, setModal] = useState<null | "account" | "tx" | Row>(null);
  const inval = () => qc.invalidateQueries();
  const fc = useQuery({ queryKey: ["forecast", days], queryFn: () => api<Forecast>(`/treasury/forecast?days=${days}`) });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api<Row[]>("/accounts") });
  const txs = useQuery({ queryKey: ["tx", acc], queryFn: () => api<Row[]>(`/transactions?limit=300${acc ? `&account_id=${acc}` : ""}`) });
  const saveAcc = useMutation({ mutationFn: (b: Record<string, unknown>) => api("/accounts", "POST", b), onSuccess: () => { inval(); setModal(null); } });
  const saveTx = useMutation({ mutationFn: (b: Record<string, unknown>) => api("/transactions", "POST", b), onSuccess: () => { inval(); setModal(null); } });
  const delTx = useMutation({ mutationFn: (id: number) => api(`/transactions/${id}`, "DELETE"), onSuccess: inval });
  const delAcc = useMutation({ mutationFn: (id: number) => api(`/accounts/${id}`, "DELETE"), onSuccess: () => { setAcc(""); inval(); } });
  const accs = accounts.data ?? [];
  const f = fc.data;
  return (
    <>
      <PageHeader title="Trésorerie" subtitle="Solde actuel et prévision : factures à encaisser, impôts et abonnements à venir." action={<div className="flex gap-2"><Button variant="ghost" onClick={() => setModal("account")}>+ Compte</Button><Button disabled={!accs.length} onClick={() => setModal("tx")}>+ Mouvement</Button></div>} />
      {!f ? <Loading /> : (
        <div className="mb-6 grid gap-6 lg:grid-cols-[1fr_340px]">
          <Card title="Prévision de trésorerie" action={<select className="!w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={30}>30 jours</option><option value={90}>90 jours</option><option value={180}>6 mois</option></select>}>
            <div className="mb-4 grid grid-cols-3 gap-3 text-sm">
              <div><p className="text-xs text-slate-400">Solde actuel</p><p className="text-lg font-bold">{fmtMoney(f.balance)}</p></div>
              <div><p className="text-xs text-slate-400">Point bas prévu</p><p className={cx("text-lg font-bold", f.lowest < 0 && "text-red-600")}>{fmtMoney(f.lowest)}</p></div>
              <div><p className="text-xs text-slate-400">Dans {days} j</p><p className="text-lg font-bold">{fmtMoney(f.end_balance)}</p></div>
            </div>
            <Chart series={f.series} />
            {f.lowest < 0 && <p className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700"> Le solde prévu passe en négatif : relancez vos factures ou décalez des dépenses.</p>}
          </Card>
          <Card title="Prochains mouvements prévus">
            {!f.events.length ? <Empty>Rien de prévu.</Empty> : <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto text-sm">{f.events.map((e, i) => (
              <li key={i} className="flex items-center justify-between gap-2 py-2"><span><span className="block">{e.label}</span><span className="text-xs text-slate-400">{fmtDate(e.date)} · {TYPE[e.type]}</span></span><b className={e.amount < 0 ? "text-red-600" : "text-emerald-800"}>{fmtMoney(e.amount)}</b></li>))}</ul>}
          </Card>
        </div>
      )}
      <Card title="Mouvements bancaires" action={<div className="flex items-center gap-2">
        <select className="!w-auto" value={acc} onChange={(e) => setAcc(e.target.value ? Number(e.target.value) : "")}><option value="">Tous les comptes</option>{accs.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        {acc !== "" && <CsvImportButton endpoint="/transactions/import" extra={{ account_id: acc }} label="Importer un relevé" hint="Export CSV de votre banque : colonnes Date (JJ/MM/AAAA), Libellé, Montant (ou Débit / Crédit). Les doublons sont ignorés." />}
        {acc !== "" && <Button variant="danger" onClick={() => confirm("Supprimer ce compte et ses mouvements ?") && delAcc.mutate(Number(acc))}>Supprimer le compte</Button>}</div>}>
        <ErrorMsg error={delTx.error ?? delAcc.error} />
        {!accs.length ? <Empty>Commencez par ajouter un compte bancaire (avec son solde actuel).</Empty> : !txs.data?.length ? <Empty>Aucun mouvement. Ajoutez-en un ou importez le CSV de votre banque.</Empty> : (
          <table className="w-full text-sm"><tbody className="divide-y divide-slate-100">
            {txs.data.map((t) => <tr key={t.id}><td className="py-2 pr-3 text-slate-400">{fmtDate(t.tx_date)}</td><td className="pr-3">{t.label} {t.category && <Badge>{t.category}</Badge>}</td><td className={cx("text-right font-medium", t.amount < 0 ? "text-red-600" : "text-emerald-800")}>{fmtMoney(t.amount)}</td><td className="w-8 text-right"><button className="text-xs text-red-500" onClick={() => delTx.mutate(t.id)}>✕</button></td></tr>)}
          </tbody></table>
        )}
      </Card>
      {modal === "account" && <FormModal title="Nouveau compte" fields={accountFields} initial={defaults(accountFields, { initial_balance: 0 })} onClose={() => setModal(null)} onSubmit={(b) => saveAcc.mutate(b)} busy={saveAcc.isPending} error={saveAcc.error} />}
      {modal === "tx" && <FormModal title="Nouveau mouvement" fields={txFields(accs)} initial={defaults(txFields(accs), { account_id: acc || accs[0]?.id, tx_date: new Date().toISOString().slice(0, 10) })} onClose={() => setModal(null)} onSubmit={(b) => saveTx.mutate(b)} busy={saveTx.isPending} error={saveTx.error} />}
    </>
  );
}
