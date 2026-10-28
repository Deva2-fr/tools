import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { DirectoryUser, Expense, SignatureRow, User, api, isManager, postForPdf } from "../api";
import SignaturePad from "./SignaturePad";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, PageHeader, fmtDate, fmtMoney } from "../ui";

const CATEGORIES = ["Transport", "Hébergement", "Repas", "Matériel", "Logiciels / abonnements", "Formation", "Réception / client", "Autre"];
const PAYMENTS = ["Carte bancaire perso", "Carte entreprise", "Espèces", "Virement"];

const blank = (user: User) => ({
  expense_date: new Date().toISOString().slice(0, 10), user_id: user.id as number, signature_id: null as number | null, reason: "", category: "Transport",
  project: "", payment_method: PAYMENTS[0], amount_ttc: "" as number | "", vat_rate: 20, notes: "",
});

/** Dernière signature utilisée par utilisateur : simple confort, mémorisé dans ce navigateur. */
const lastSig = {
  get: (uid: number) => { try { return Number(localStorage.getItem(`ndf-sig-${uid}`)) || null; } catch { return null; } },
  set: (uid: number, id: number | null) => { try { if (id) localStorage.setItem(`ndf-sig-${uid}`, String(id)); } catch { /* stockage indisponible */ } },
};

export default function Expenses({ user }: { user: User }) {
  const qc = useQueryClient();
  const [f, setF] = useState(blank(user));
  const [editId, setEditId] = useState<number | null>(null);
  const [done, setDone] = useState("");
  const [driveMsg, setDriveMsg] = useState("");
  const [receipt, setReceipt] = useState<File | null>(null);
  const [currentReceipt, setCurrentReceipt] = useState("");
  const [removeReceipt, setRemoveReceipt] = useState(false);
  const [fileKey, setFileKey] = useState(0); // remet à zéro le champ fichier
  const [padOpen, setPadOpen] = useState(false);
  const manager = isManager(user);
  const people = useQuery({ queryKey: ["directory"], queryFn: () => api<DirectoryUser[]>("/users/directory") });
  const sigs = useQuery({ queryKey: ["signatures", f.user_id], queryFn: () => api<SignatureRow[]>(`/expenses/signatures${manager ? `?user_id=${f.user_id}` : ""}`) });
  // Changement d'utilisateur : on propose sa dernière signature (ou sa seule signature).
  useEffect(() => {
    if (!sigs.data) return;
    setF((x) => {
      if (x.signature_id && sigs.data.some((sg) => sg.id === x.signature_id)) return x;
      const remembered = lastSig.get(x.user_id);
      const pick = sigs.data.find((sg) => sg.id === remembered) ?? (sigs.data.length === 1 ? sigs.data[0] : null);
      return { ...x, signature_id: pick?.id ?? null };
    });
  }, [sigs.data]);
  const resetFiles = () => { setReceipt(null); setCurrentReceipt(""); setRemoveReceipt(false); setFileKey((k) => k + 1); };
  const list = useQuery({ queryKey: ["expenses"], queryFn: () => api<Expense[]>("/expenses") });
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));

  const ttc = Number(f.amount_ttc) || 0;
  const ht = Math.round((ttc / (1 + f.vat_rate / 100)) * 100) / 100;

  const save = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("data", JSON.stringify({ ...f, amount_ttc: ttc }));
      if (receipt) form.append("receipt", receipt);
      if (removeReceipt && !receipt) form.append("remove_receipt", "true");
      return postForPdf(`/expenses/save${editId ? `?expense_id=${editId}` : ""}`, form);
    },
    onSuccess: (r) => {
      lastSig.set(f.user_id, f.signature_id);
      resetFiles();
      setDone(`Note enregistrée – « ${r.filename} » téléchargé${r.drive === "ok" ? " et déposé dans Google Drive (Comptabilité › Note de frais)" : ""}.`);
      setDriveMsg(r.drive === "not_configured" ? "Google Drive n'est pas configuré : le PDF n'a pas été déposé dans le Drive (Paramètres → Intégrations → Google Drive)." : r.drive.startsWith("error:") ? `Le PDF n'a pas pu être déposé dans Google Drive : ${r.drive.slice(6)}` : "");
      setEditId(null);
      setF(blank(user));
      qc.invalidateQueries({ queryKey: ["expenses"] });
    },
    onError: () => { setDone(""); setDriveMsg(""); },
  });
  const retry = useMutation({ mutationFn: (id: number) => api(`/expenses/${id}/drive`, "POST"), onSuccess: () => qc.invalidateQueries({ queryKey: ["expenses"] }) });
  const del = useMutation({ mutationFn: (id: number) => api(`/expenses/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries({ queryKey: ["expenses"] }) });

  const edit = (e: Expense) => {
    setEditId(e.id);
    setDone("");
    setF({ expense_date: e.expense_date, user_id: e.user_id ?? user.id, signature_id: e.signature_id, reason: e.reason, category: e.category, project: e.project, payment_method: e.payment_method, amount_ttc: e.amount_ttc, vat_rate: e.vat_rate, notes: e.notes });
    resetFiles();
    setCurrentReceipt(e.has_receipt ? e.receipt_name : "");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <PageHeader title="Notes de frais" subtitle="Remplissez les champs, cliquez sur Enregistrer : le PDF est généré, téléchargé et rangé dans Google Drive (Administration › Comptabilité › Note de frais)." />
      <Card title={editId ? `Modifier la note n°${editId}` : "Nouvelle note de frais"}>
        <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Date de la dépense *"><input type="date" required value={f.expense_date} onChange={(e) => set("expense_date", e.target.value)} /></Field>
          <Field label="Utilisateur *" hint={manager ? "La personne qui a avancé les frais" : undefined}>
            <select required disabled={!manager} value={f.user_id} onChange={(e) => setF((x) => ({ ...x, user_id: Number(e.target.value), signature_id: null }))}>
              {(people.data ?? [{ id: user.id, name: user.name || user.email, email: user.email }]).map((p) => <option key={p.id} value={p.id}>{p.name}{p.name !== p.email ? ` (${p.email})` : ""}</option>)}
            </select>
          </Field>
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
          <div className="sm:col-span-2 lg:col-span-3 grid gap-4 border-t border-slate-100 pt-4 sm:grid-cols-2">
            <Field label="Signature" hint="Imprimée dans le cadre « Signature du collaborateur »">
              <div className="flex items-center gap-2">
                <select value={f.signature_id ?? ""} onChange={(e) => set("signature_id", e.target.value ? Number(e.target.value) : null)}>
                  <option value="">— Sans signature —</option>
                  {(sigs.data ?? []).map((sg) => <option key={sg.id} value={sg.id}>{sg.name}</option>)}
                </select>
                <Button type="button" variant="soft" className="shrink-0 whitespace-nowrap" onClick={() => setPadOpen(true)}>+ Nouvelle</Button>
              </div>
              {f.signature_id && <img alt="Signature choisie" src={`/api/expenses/signatures/${f.signature_id}/image`} className="mt-2 h-14 rounded border border-slate-200 bg-white object-contain p-1" />}
            </Field>
            <Field label="Justificatif" hint="Ticket, facture… PDF, JPG ou PNG (10 Mo max.) : ajouté à la fin du PDF">
              <input key={fileKey} type="file" accept="application/pdf,image/jpeg,image/png" onChange={(e) => setReceipt(e.target.files?.[0] ?? null)} />
              {currentReceipt && !receipt && (
                <p className="mt-2 flex flex-wrap items-center gap-3 text-xs">
                  <span className={removeReceipt ? "text-slate-400 line-through" : "text-slate-600"}>Actuel : {currentReceipt}</span>
                  <a className="text-brand-600" href={`/api/expenses/${editId}/receipt`} target="_blank" rel="noreferrer">Voir</a>
                  <label className="flex items-center gap-1 text-red-700"><input type="checkbox" className="!w-auto" checked={removeReceipt} onChange={(e) => setRemoveReceipt(e.target.checked)} /> Retirer</label>
                </p>
              )}
            </Field>
          </div>
          <div className="space-y-3 sm:col-span-2 lg:col-span-3">
            <ErrorMsg error={save.error} />
            {done && <p className="rounded border border-emerald-700/30 px-3 py-2 text-sm text-emerald-800">{done}</p>}
            {driveMsg && <p className="rounded border border-amber-600/30 bg-amber-50 px-3 py-2 text-sm text-amber-800">{driveMsg}</p>}
            <div className="flex justify-end gap-2">
              {editId && <Button type="button" variant="ghost" onClick={() => { setEditId(null); setF(blank(user)); resetFiles(); }}>Annuler la modification</Button>}
              <Button type="submit" busy={save.isPending}> Enregistrer et télécharger le PDF</Button>
            </div>
          </div>
        </form>
      </Card>
      {padOpen && (
        <SignaturePad userId={manager ? f.user_id : null} defaultName={people.data?.find((p) => p.id === f.user_id)?.name ?? user.name}
          onClose={() => setPadOpen(false)}
          onCreated={(sg) => { setPadOpen(false); qc.invalidateQueries({ queryKey: ["signatures"] }); set("signature_id", sg.id); }} />
      )}
      <Card title="Historique" className="mt-6">
        <ErrorMsg error={retry.error} />
        {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucune note de frais pour l'instant.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Date</th><th>Utilisateur</th><th>Motif</th><th>Catégorie</th><th className="text-right">TTC</th><th className="text-right">TVA</th><th /></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.map((e) => (
                  <tr key={e.id}>
                    <td className="py-2.5">{fmtDate(e.expense_date)}</td><td>{e.employee}</td><td className="max-w-xs truncate">{e.reason}</td><td><Badge>{e.category || "—"}</Badge></td>
                    <td className="text-right font-medium">{fmtMoney(e.amount_ttc)}</td><td className="text-right text-slate-500">{fmtMoney(e.amount_vat)}</td>
                    <td className="space-x-3 whitespace-nowrap text-right text-xs">
                      {e.has_pdf && <a className="text-brand-600" href={`/api/expenses/${e.id}/pdf`}>PDF</a>}
                      {e.has_receipt && <a className="text-brand-600" href={`/api/expenses/${e.id}/receipt`} target="_blank" rel="noreferrer" title={e.receipt_name}>Justificatif</a>}
                      {e.drive_link ? <a className="text-brand-600" href={e.drive_link} target="_blank" rel="noreferrer noopener">Drive ↗</a>
                        : e.has_pdf && <button className="text-amber-700" disabled={retry.isPending} onClick={() => retry.mutate(e.id)} title="Le PDF n'est pas encore dans Google Drive">Envoyer dans Drive</button>}
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
