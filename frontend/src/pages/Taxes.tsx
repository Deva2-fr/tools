import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Tax, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDate, fmtMoney } from "../ui";

const CATS: Record<string, string> = { tva: "TVA", is: "Impôt sociétés", cfe: "CFE", urssaf: "URSSAF", social: "Social", comptes: "Comptes annuels", autre: "Autre" };
const REC: Record<string, string> = { none: "Une seule fois", monthly: "Chaque mois", quarterly: "Chaque trimestre", yearly: "Chaque année" };
const blank = { title: "", category: "tva", due_date: "", amount: null as number | null, recurrence: "none", reminder_days: "30,7,1", notes: "", status: "todo" };

function TaxModal({ tax, onClose }: { tax?: Tax; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState(tax ? { title: tax.title, category: tax.category, due_date: tax.due_date, amount: tax.amount, recurrence: tax.recurrence, reminder_days: tax.reminder_days, notes: tax.notes, status: tax.status as string } : blank);
  const save = useMutation({
    mutationFn: () => (tax ? api(`/taxes/${tax.id}`, "PUT", f) : api("/taxes", "POST", f)),
    onSuccess: () => { qc.invalidateQueries(); onClose(); },
  });
  return (
    <Modal title={tax ? "Modifier l'échéance" : "Nouvelle échéance"} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <Field label="Intitulé *"><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="TVA – janvier" /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Type"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{Object.entries(CATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Date limite *"><input type="date" required value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
          <Field label="Montant estimé (€)"><input type="number" step="0.01" value={f.amount ?? ""} onChange={(e) => setF({ ...f, amount: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
          <Field label="Répétition"><select value={f.recurrence} onChange={(e) => setF({ ...f, recurrence: e.target.value })}>{Object.entries(REC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
        </div>
        <Field label="Me prévenir (jours avant)" hint="Séparés par des virgules. Ex : 30,7,1"><input value={f.reminder_days} onChange={(e) => setF({ ...f, reminder_days: e.target.value })} /></Field>
        <Field label="Notes"><textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <ErrorMsg error={save.error} />
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" busy={save.isPending}>Enregistrer</Button></div>
      </form>
    </Modal>
  );
}

export default function Taxes() {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Tax | "new" | null>(null);
  const [showPaid, setShowPaid] = useState(false);
  const [msg, setMsg] = useState("");
  const { data, isLoading } = useQuery({ queryKey: ["taxes"], queryFn: () => api<Tax[]>("/taxes") });
  const inval = () => qc.invalidateQueries();
  const paid = useMutation({ mutationFn: (id: number) => api(`/taxes/${id}/paid`, "POST"), onSuccess: inval });
  const del = useMutation({ mutationFn: (id: number) => api(`/taxes/${id}`, "DELETE"), onSuccess: inval });
  const gen = useMutation({
    mutationFn: (year: number) => api<{ created: number }>(`/taxes/generate?year=${year}`, "POST"),
    onSuccess: (r) => { setMsg(`${r.created} échéance(s) ajoutée(s). Vérifiez les dates avec votre comptable.`); inval(); },
  });

  const rows = (data ?? []).filter((t) => showPaid || t.status === "todo");
  const year = new Date().getFullYear();
  return (
    <>
      <PageHeader title="Impôts, TVA & déclarations" subtitle="Ne ratez plus une échéance : le Hub vous prévient avant chaque date limite."
        action={<div className="flex gap-2">
          <a href="/api/taxes/calendar.ics"><Button variant="ghost" type="button">📆 Exporter vers mon agenda</Button></a>
          <Button onClick={() => setEdit("new")}>+ Échéance</Button></div>} />
      {msg && <p className="mb-4 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">{msg}</p>}
      <ErrorMsg error={gen.error} />
      <Card title="Échéances" action={<label className="flex items-center gap-2 text-xs text-slate-500"><input type="checkbox" checked={showPaid} onChange={(e) => setShowPaid(e.target.checked)} /> Afficher les payées</label>}>
        {isLoading ? <Loading /> : rows.length === 0 ? (
          <div className="space-y-3 text-center">
            <Empty>Aucune échéance à venir.</Empty>
            <div className="flex justify-center gap-2">
              <Button variant="soft" busy={gen.isPending} onClick={() => gen.mutate(year)}>Pré-remplir {year} (TVA, IS, CFE…)</Button>
              <Button variant="soft" busy={gen.isPending} onClick={() => gen.mutate(year + 1)}>Pré-remplir {year + 1}</Button>
            </div>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((t) => (
              <li key={t.id} className={`flex flex-wrap items-center justify-between gap-3 py-3 ${t.status === "paid" ? "opacity-50" : ""}`}>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">{t.title}</p>
                  <p className="text-xs text-slate-400">{CATS[t.category] ?? t.category} · {fmtDate(t.due_date)}{t.recurrence !== "none" && ` · ${REC[t.recurrence]}`}{t.amount != null && ` · ${fmtMoney(t.amount)}`}</p>
                </div>
                <div className="flex items-center gap-3">
                  {t.status === "paid" ? <Badge tone="green">Payée</Badge> : <Badge tone={t.days_left < 0 ? "red" : t.days_left <= 7 ? "amber" : "slate"}>{t.days_left < 0 ? `En retard de ${-t.days_left} j` : t.days_left === 0 ? "Aujourd'hui" : `Dans ${t.days_left} j`}</Badge>}
                  {t.status === "todo" && <Button variant="soft" onClick={() => paid.mutate(t.id)}>✔ C'est payé</Button>}
                  <button className="text-xs text-brand-600" onClick={() => setEdit(t)}>Modifier</button>
                  <button className="text-xs text-red-600" onClick={() => confirm("Supprimer cette échéance ?") && del.mutate(t.id)}>Supprimer</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {rows.length > 0 && <p className="mt-4 text-xs text-slate-400">Les échéances pré-remplies sont indicatives (société à l'IS, exercice au 31/12). Les dates exactes de TVA et d'URSSAF dépendent de votre régime : confirmez-les avec votre comptable puis ajustez-les ici. <button className="text-brand-600 underline" onClick={() => gen.mutate(year + 1)}>Pré-remplir {year + 1}</button></p>}
      {edit && <TaxModal tax={edit === "new" ? undefined : edit} onClose={() => setEdit(null)} />}
    </>
  );
}
