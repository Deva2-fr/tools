import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { DirectoryUser, Expense, SignatureRow, Signers, User, api, apiUpload, isManager, postForPdf } from "../api";
import SignaturePad from "./SignaturePad";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, PageHeader, fmtDate, fmtMoney } from "../ui";

const CATEGORIES = ["Transport", "Hébergement", "Repas", "Matériel", "Logiciels / abonnements", "Formation", "Réception / client", "Autre"];
const PAYMENTS = ["Carte bancaire perso", "Carte entreprise", "Espèces", "Virement"];

const blank = (user: User) => ({
  expense_date: new Date().toISOString().slice(0, 10), user_id: user.id as number, signature_id: null as number | null,
  president_signature_id: null as number | null, partner_signature_id: null as number | null, reason: "", category: "Transport",
  project: "", payment_method: PAYMENTS[0], amount_ttc: "" as number | "", vat_rate: 20, notes: "",
});

/** Dernière signature utilisée par utilisateur : simple confort, mémorisé dans ce navigateur. */
const lastSig = {
  get: (uid: number) => { try { return Number(localStorage.getItem(`ndf-sig-${uid}`)) || null; } catch { return null; } },
  set: (uid: number, id: number | null) => { try { if (id) localStorage.setItem(`ndf-sig-${uid}`, String(id)); } catch { /* stockage indisponible */ } },
};

type SlotKey = "signature_id" | "president_signature_id" | "partner_signature_id";

/** Une case de signature : les signatures de la personne attendue (demandeur, président ou associé). */
function SignatureSlot({ label, owner, value, onChange, canSign, onNew }: {
  label: string; owner: { id: number; name: string } | null; value: number | null;
  onChange: (id: number | null) => void; canSign: boolean; onNew: () => void;
}) {
  const sigs = useQuery({
    queryKey: ["signatures", owner?.id],
    queryFn: () => api<SignatureRow[]>(`/expenses/signatures?user_id=${owner!.id}`),
    enabled: !!owner,
  });
  const qc = useQueryClient();
  const mine = (sigs.data ?? []).filter((sg) => sg.user_id === owner?.id);
  const del = useMutation({
    mutationFn: (sid: number) => api(`/expenses/signatures/${sid}`, "DELETE"),
    onSuccess: () => { onChange(null); qc.invalidateQueries({ queryKey: ["signatures"] }); },
  });
  return (
    <div className="rounded-md border border-slate-200 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mb-2 text-sm text-slate-700">{owner?.name ?? <span className="text-amber-700">À désigner dans Paramètres → Intégrations</span>}</p>
      {owner && (canSign ? (
        <div className="flex items-center gap-2">
          <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— Pas encore signé —</option>
            {mine.map((sg) => <option key={sg.id} value={sg.id}>{sg.name}</option>)}
          </select>
          <Button type="button" variant="soft" className="shrink-0 whitespace-nowrap" onClick={onNew}>+ Nouvelle</Button>
        </div>
      ) : <p className="text-xs text-slate-400">{value ? "Signé" : `En attente de la signature de ${owner.name}`}</p>)}
      {value ? <img alt={`Signature – ${label}`} src={`/api/expenses/signatures/${value}/image`} className="mt-2 h-14 w-full rounded border border-slate-100 bg-white object-contain p-1" /> : null}
      {value && canSign ? (
        <button type="button" className="mt-1 text-xs text-red-600" disabled={del.isPending}
          onClick={() => confirm("Supprimer définitivement cette signature ? Elle disparaîtra des notes de frais où elle est utilisée (les PDF déjà générés ne changent pas).") && del.mutate(value)}>
          Supprimer cette signature
        </button>
      ) : null}
      <ErrorMsg error={del.error} />
    </div>
  );
}

export default function Expenses({ user }: { user: User }) {
  const qc = useQueryClient();
  const [f, setF] = useState(blank(user));
  const [editId, setEditId] = useState<number | null>(null);
  const [done, setDone] = useState("");
  const [driveMsg, setDriveMsg] = useState("");
  const [newFiles, setNewFiles] = useState<File[]>([]);
  const [currentFiles, setCurrentFiles] = useState<{ id: number; name: string }[]>([]);
  const [removeIds, setRemoveIds] = useState<number[]>([]);
  const [fileKey, setFileKey] = useState(0); // remet à zéro le champ fichier
  const [pad, setPad] = useState<{ slot: SlotKey; owner: { id: number; name: string } } | null>(null);
  const signers = useQuery({ queryKey: ["expense-signers"], queryFn: () => api<Signers>("/expenses/signers") });
  const isSigner = [signers.data?.president?.id, signers.data?.partner?.id].includes(user.id);
  const manager = isManager(user) || isSigner;
  const people = useQuery({ queryKey: ["directory"], queryFn: () => api<DirectoryUser[]>("/users/directory") });
  const sigs = useQuery({ queryKey: ["signatures", f.user_id], queryFn: () => api<SignatureRow[]>(`/expenses/signatures?user_id=${f.user_id}`) });
  // Changement d'utilisateur : on propose sa dernière signature (ou sa seule signature).
  useEffect(() => {
    if (!sigs.data) return;
    setF((x) => {
      const own = sigs.data.filter((sg) => sg.user_id === x.user_id);
      if (x.signature_id && own.some((sg) => sg.id === x.signature_id)) return x;
      const remembered = lastSig.get(x.user_id);
      const pick = own.find((sg) => sg.id === remembered) ?? (own.length === 1 ? own[0] : null);
      return { ...x, signature_id: pick?.id ?? null };
    });
  }, [sigs.data]);
  const resetFiles = () => { setNewFiles([]); setCurrentFiles([]); setRemoveIds([]); setFileKey((k) => k + 1); };
  const keptCount = currentFiles.length - removeIds.length + newFiles.length;
  const list = useQuery({ queryKey: ["expenses"], queryFn: () => api<Expense[]>("/expenses") });
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));
  // Lecture du justificatif par l'IA : pré-remplit date, montant, TVA, motif et catégorie (à vérifier).
  const [aiMsg, setAiMsg] = useState("");
  const aiRead = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append("file", file); return apiUpload<{ expense_date: string; amount_ttc: number; vat_rate: number; reason: string; category: string }>("/expenses/ai-read", fd); },
    onSuccess: (r) => {
      setF((x) => ({ ...x, expense_date: r.expense_date || x.expense_date, amount_ttc: r.amount_ttc || x.amount_ttc, vat_rate: r.vat_rate, reason: r.reason || x.reason, category: r.category || x.category }));
      setAiMsg("✨ Champs pré-remplis par l'IA à partir du justificatif : vérifiez-les avant d'enregistrer.");
    },
  });

  const requester = people.data?.find((p) => p.id === f.user_id);
  const ttc = Number(f.amount_ttc) || 0;
  const ht = Math.round((ttc / (1 + f.vat_rate / 100)) * 100) / 100;

  const save = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("data", JSON.stringify({ ...f, amount_ttc: ttc }));
      newFiles.forEach((file) => form.append("receipts", file));
      removeIds.forEach((id) => form.append("remove_receipt_ids", String(id)));
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
    setF({ expense_date: e.expense_date, user_id: e.user_id ?? user.id, signature_id: e.signature_id, president_signature_id: e.president_signature_id, partner_signature_id: e.partner_signature_id, reason: e.reason, category: e.category, project: e.project, payment_method: e.payment_method, amount_ttc: e.amount_ttc, vat_rate: e.vat_rate, notes: e.notes });
    resetFiles();
    setCurrentFiles(e.receipt_files);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <PageHeader title="Notes de frais" subtitle="Remplissez la note, faites-la signer (demandeur, président, associé), joignez les justificatifs : le PDF est généré, téléchargé et rangé dans Google Drive (Administration › Comptabilité › Note de frais)." />
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
          <div className="sm:col-span-2 lg:col-span-3 border-t border-slate-100 pt-4">
            <p className="mb-2 text-sm font-medium text-slate-800">Signatures <span className="font-normal text-slate-400">— imprimées dans les trois cadres du PDF</span></p>
            <div data-tour="exp-signatures" className="grid gap-3 md:grid-cols-3">
              {([
                ["signature_id", "Le demandeur", requester ? { id: requester.id, name: requester.name } : { id: user.id, name: user.name || user.email }],
                ["president_signature_id", "Le président", signers.data?.president ?? null],
                ["partner_signature_id", "L'associé", signers.data?.partner ?? null],
              ] as const).map(([slot, label, owner]) => (
                <SignatureSlot key={slot} label={label} owner={owner} value={f[slot]} onChange={(v) => set(slot, v)}
                  canSign={!!owner && (manager || owner.id === user.id)} onNew={() => owner && setPad({ slot, owner })} />
              ))}
            </div>
          </div>
          <div data-tour="exp-receipts" className="sm:col-span-2 lg:col-span-3">
            <Field label={`Justificatifs (${keptCount}/10)`} hint="Tickets, factures… PDF, JPG ou PNG (10 Mo max. chacun) : ajoutés à la fin du PDF, dans l'ordre">
              <input key={fileKey} type="file" multiple accept="application/pdf,image/jpeg,image/png" onChange={(e) => { const picked = Array.from(e.target.files ?? []); setNewFiles((x) => [...x, ...picked]); setFileKey((k) => k + 1); }} />
            </Field>
            {newFiles.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button type="button" variant="soft" busy={aiRead.isPending} onClick={() => aiRead.mutate(newFiles[newFiles.length - 1])}>✨ Remplir avec l'IA</Button>
                <span className="text-xs text-slate-500">{aiMsg || "Lit le dernier justificatif ajouté : date, montant TTC, TVA, motif, catégorie."}</span>
              </div>
            )}
            <ErrorMsg error={aiRead.error} />
            {(currentFiles.length > 0 || newFiles.length > 0) && (
              <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 text-sm">
                {currentFiles.map((r) => {
                  const gone = removeIds.includes(r.id);
                  return (
                    <li key={`c${r.id}`} className="flex items-center justify-between px-3 py-1.5">
                      <span className={gone ? "text-slate-400 line-through" : ""}>{r.name}</span>
                      <span className="flex gap-3 text-xs">
                        <a className="text-brand-600" href={`/api/expenses/${editId}/receipts/${r.id}`} target="_blank" rel="noreferrer">Voir</a>
                        <button type="button" className={gone ? "text-brand-600" : "text-red-600"} onClick={() => setRemoveIds((x) => (gone ? x.filter((i) => i !== r.id) : [...x, r.id]))}>{gone ? "Garder" : "Retirer"}</button>
                      </span>
                    </li>
                  );
                })}
                {newFiles.map((file, i) => (
                  <li key={`n${i}`} className="flex items-center justify-between px-3 py-1.5">
                    <span>{file.name} <Badge tone="blue">nouveau</Badge></span>
                    <button type="button" className="text-xs text-red-600" onClick={() => setNewFiles((x) => x.filter((_, j) => j !== i))}>Retirer</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="space-y-3 sm:col-span-2 lg:col-span-3">
            <ErrorMsg error={save.error} />
            {done && <p className="rounded border border-emerald-700/30 px-3 py-2 text-sm text-emerald-800">{done}</p>}
            {driveMsg && <p className="rounded border border-amber-600/30 bg-amber-50 px-3 py-2 text-sm text-amber-800">{driveMsg}</p>}
            <div className="flex flex-wrap justify-end gap-2">
              {editId && <Button type="button" variant="ghost" onClick={() => { setEditId(null); setF(blank(user)); resetFiles(); }}>Annuler la modification</Button>}
              <Button data-tour="exp-save" type="submit" busy={save.isPending}> Enregistrer et télécharger le PDF</Button>
            </div>
          </div>
        </form>
      </Card>
      {pad && (
        <SignaturePad userId={pad.owner.id === user.id ? null : pad.owner.id} defaultName={pad.owner.name}
          onClose={() => setPad(null)}
          onCreated={(sg) => { const slot = pad.slot; setPad(null); qc.invalidateQueries({ queryKey: ["signatures"] }); set(slot, sg.id); }} />
      )}
      <Card title="Historique" className="mt-6">
        <ErrorMsg error={retry.error} />
        {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucune note de frais pour l'instant.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead><tr className="border-b border-slate-100 text-left text-xs uppercase text-slate-400"><th className="py-2">Date</th><th>Utilisateur</th><th>Motif</th><th>Catégorie</th><th className="text-right">TTC</th><th className="text-right">TVA</th><th /></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.map((e) => (
                  <tr key={e.id}>
                    <td className="py-2.5">{fmtDate(e.expense_date)}</td><td>{e.employee}</td><td className="max-w-xs truncate">{e.reason}</td><td><Badge>{e.category || "—"}</Badge></td>
                    <td className="text-right font-medium">{fmtMoney(e.amount_ttc)}</td><td className="text-right text-slate-500">{fmtMoney(e.amount_vat)}</td>
                    <td className="space-x-3 whitespace-nowrap text-right text-xs">
                      {e.has_pdf && <a className="text-brand-600" href={`/api/expenses/${e.id}/pdf`}>PDF</a>}
                      {e.receipt_files.length > 0 && <span className="text-slate-400" title={e.receipt_files.map((r) => r.name).join(", ")}>{e.receipt_files.length} justif.</span>}
                      <span className="text-slate-400" title="Demandeur · Président · Associé">{[e.signature_id, e.president_signature_id, e.partner_signature_id].filter(Boolean).length}/3 sign.</span>
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
