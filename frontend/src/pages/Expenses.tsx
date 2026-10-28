import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Expense, User, api, postForPdf } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, PageHeader, fmtDate, fmtMoney } from "../ui";

const CATEGORIES = ["Transport", "Hébergement", "Repas", "Matériel", "Logiciels / abonnements", "Formation", "Réception / client", "Autre"];
const PAYMENTS = ["Carte bancaire perso", "Carte entreprise", "Espèces", "Virement"];

const blank = (user: User) => ({
  expense_date: new Date().toISOString().slice(0, 10), employee: user.name || "", reason: "", category: "Transport",
  project: "", payment_method: PAYMENTS[0], amount_ttc: "" as number | "", vat_rate: 20, notes: "",
});

export default function Expenses({ user }: { user: User }) {
  const qc = useQueryClient();
  const [f, setF] = useState(blank(user));
  const [editId, setEditId] = useState<number | null>(null);
  const [done, setDone] = useState("");
  const list = useQuery({ queryKey: ["expenses"], queryFn: () => api<Expense[]>("/expenses") });
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));

  const ttc = Number(f.amount_ttc) || 0;
  const ht = Math.round((ttc / (1 + f.vat_rate / 100)) * 100) / 100;

  const save = useMutation({
    mutationFn: () => postForPdf(`/expenses/save${editId ? `?expense_id=${editId}` : ""}`, { ...f, amount_ttc: ttc }),
    onSuccess: (r) => {
      setDone(` Note enregistrée – « ${r.filename} » téléchargé.`);
      setEditId(null);
      setF(blank(user));
      qc.invalidateQueries({ queryKey: ["expenses"] });
    },
    onError: () => setDone(""),
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/expenses/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries({ queryKey: ["expenses"] }) });

  const edit = (e: Expense) => {
    setEditId(e.id);
    setDone("");
    setF({ expense_date: e.expense_date, employee: e.employee, reason: e.reason, category: e.category, project: e.project, payment_method: e.payment_method, amount_ttc: e.amount_ttc, vat_rate: e.vat_rate, notes: e.notes });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <PageHeader title="Notes de frais" subtitle="Remplissez les champs, cliquez sur Enregistrer : le PDF se télécharge, rempli automatiquement." />
      <Card title={editId ? `Modifier la note n°${editId}` : "Nouvelle note de frais"}>
        <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Date de la dépense *"><input type="date" required value={f.expense_date} onChange={(e) => set("expense_date", e.target.value)} /></Field>
          <Field label="Nom du salarié / associé *"><input required value={f.employee} onChange={(e) => set("employee", e.target.value)} /></Field>
          <Field label="Catégorie">
            <select value={f.category} onChange={(e) => set("category", e.target.value)}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
          </Field>
          <div className="sm:col-span-2 lg:col-span-3"><Field label="Motif *" hint="Ex : Train Paris–Lyon, rendez-vous client Formasyl"><input required value={f.reason} onChange={(e) => set("reason", e.target.value)} /></Field></div>
          <Field label="Montant TTC (€) *"><input type="number" step="0.01" min="0.01" required value={f.amount_ttc} onChange={(e) => set("amount_ttc", e.target.value === "" ? "" : Number(e.target.value))} /></Field>
          <Field label="Taux de TVA">
            <select value={f.vat_rate} onChange={(e) => set("vat_rate", Number(e.target.value))}>
              {[20, 10, 5.5, 2.1, 0].map((r) => <option key={r} value={r}>{r} %</option>)}
            </select>
          </Field>
          <div className="flex items-end"><p className="rounded bg-slate-50 px-3 py-2 text-sm text-slate-600">HT : <b>{fmtMoney(ht)}</b> · TVA : <b>{fmtMoney(Math.round((ttc - ht) * 100) / 100)}</b></p></div>
          <Field label="Moyen de paiement">
            <select value={f.payment_method} onChange={(e) => set("payment_method", e.target.value)}>{PAYMENTS.map((c) => <option key={c}>{c}</option>)}</select>
          </Field>
          <Field label="Projet concerné" hint="Facultatif"><input value={f.project} onChange={(e) => set("project", e.target.value)} /></Field>
          <Field label="Remarques"><input value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
          <div className="space-y-3 sm:col-span-2 lg:col-span-3">
            <ErrorMsg error={save.error} />
            {done && <p className="rounded border border-emerald-700/30 px-3 py-2 text-sm text-emerald-800">{done}</p>}
            <div className="flex justify-end gap-2">
              {editId && <Button type="button" variant="ghost" onClick={() => { setEditId(null); setF(blank(user)); }}>Annuler la modification</Button>}
              <Button type="submit" busy={save.isPending}> Enregistrer et télécharger le PDF</Button>
            </div>
          </div>
        </form>
      </Card>
      <Card title="Historique" className="mt-6">
        {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucune note de frais pour l'instant.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Date</th><th>Salarié</th><th>Motif</th><th>Catégorie</th><th className="text-right">TTC</th><th className="text-right">TVA</th><th /></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.map((e) => (
                  <tr key={e.id}>
                    <td className="py-2.5">{fmtDate(e.expense_date)}</td><td>{e.employee}</td><td className="max-w-xs truncate">{e.reason}</td><td><Badge>{e.category || "—"}</Badge></td>
                    <td className="text-right font-medium">{fmtMoney(e.amount_ttc)}</td><td className="text-right text-slate-500">{fmtMoney(e.amount_vat)}</td>
                    <td className="space-x-3 whitespace-nowrap text-right text-xs">
                      {e.has_pdf && <a className="text-brand-600" href={`/api/expenses/${e.id}/pdf`}>PDF</a>}
                      <button className="text-brand-600" onClick={() => edit(e)}>Modifier</button>
                      <button className="text-red-600" onClick={() => confirm("Supprimer cette note ?") && del.mutate(e.id)}>Supprimer</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
