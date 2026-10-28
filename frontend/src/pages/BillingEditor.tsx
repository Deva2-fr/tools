import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Row, api, openPdf } from "../api";
import { useRefOptions } from "../components";
import { Badge, Button, Card, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDate, fmtMoney } from "../ui";
import { STATUS } from "./Billing";

interface Line { description: string; quantity: number; unit_price: number; vat_rate: number }
const blankLine = (): Line => ({ description: "", quantity: 1, unit_price: 0, vat_rate: 20 });
const today = () => new Date().toISOString().slice(0, 10);
const r2 = (n: number) => Math.round(n * 100) / 100;

export function totals(lines: Line[]) {
  const by: Record<number, number> = {};
  for (const l of lines) by[l.vat_rate] = (by[l.vat_rate] ?? 0) + r2(l.quantity * l.unit_price);
  const rows = Object.entries(by).map(([rate, base]) => ({ rate: Number(rate), base: r2(base), vat: r2((base * Number(rate)) / 100) }));
  const ht = r2(rows.reduce((a, r) => a + r.base, 0));
  const vat = r2(rows.reduce((a, r) => a + r.vat, 0));
  return { rows, ht, vat, ttc: r2(ht + vat) };
}

interface Proposal { title: string; lines: Line[]; notes: string; changes: string[] }

/** Amélioration du devis par l'IA : on demande, on compare, on applique (rien n'est enregistré seul). */
function AiImprove({ docId, current, onApply, onClose }: {
  docId: number; current: { title: string; notes: string; lines: Line[] }; onApply: (p: Proposal) => void; onClose: () => void;
}) {
  const [instructions, setInstructions] = useState("");
  const ask = useMutation({ mutationFn: () => api<Proposal>(`/billing/${docId}/ai-improve`, "POST", { ...current, instructions }) });
  const p = ask.data;
  const before = totals(current.lines);
  const after = p ? totals(p.lines) : null;
  return (
    <Modal title="Améliorer le devis avec l'IA" onClose={onClose} wide>
      <div className="space-y-4 text-sm">
        <Field label="Consigne (facultatif)" hint="Ex : détaille le périmètre de chaque prestation, ajoute les conditions de paiement, ton plus commercial…">
          <textarea rows={2} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Laissez vide pour une relecture générale : intitulés, clarté, conditions." />
        </Field>
        <div className="flex items-center gap-3">
          <Button busy={ask.isPending} onClick={() => ask.mutate()}>{p ? "Proposer à nouveau" : "Proposer une version améliorée"}</Button>
          <span className="text-xs text-slate-400">Les prix, quantités et taux de TVA ne changent pas, sauf si vous le demandez.</span>
        </div>
        <ErrorMsg error={ask.error} />
        {p && after && (
          <div className="space-y-3 rounded border border-brand-600/30 bg-brand-50/40 p-4">
            {p.changes.length > 0 && <ul className="list-disc pl-5 text-xs text-slate-600">{p.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>}
            <p><span className="text-slate-400">Objet : </span><b>{p.title}</b></p>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs uppercase text-slate-400"><th className="py-1">Désignation</th><th className="text-right">Qté</th><th className="text-right">PU HT</th><th className="text-right">TVA</th></tr></thead>
              <tbody className="divide-y divide-slate-200">
                {p.lines.map((l, i) => (
                  <tr key={i}><td className="whitespace-pre-line py-1.5 pr-3">{l.description}</td><td className="text-right">{l.quantity}</td><td className="text-right">{fmtMoney(l.unit_price)}</td><td className="text-right">{l.vat_rate} %</td></tr>
                ))}
              </tbody>
            </table>
            {p.notes && <p className="whitespace-pre-line text-xs text-slate-600"><span className="text-slate-400">Notes / conditions : </span>{p.notes}</p>}
            <p className={after.ht !== before.ht ? "font-medium text-amber-700" : "text-xs text-slate-500"}>
              Total HT : {fmtMoney(before.ht)} → {fmtMoney(after.ht)}{after.ht !== before.ht && " (le total a changé : vérifiez les prix)"}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Garder ma version</Button>
              <Button onClick={() => { onApply(p); onClose(); }}>Appliquer au devis</Button>
            </div>
            <p className="text-right text-xs text-slate-400">Pensez ensuite à enregistrer.</p>
          </div>
        )}
      </div>
    </Modal>
  );
}

export default function BillingEditor() {
  const { id } = useParams();
  const isNew = !id;
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const doc = useQuery({ queryKey: ["billing-doc", id], queryFn: () => api<Row>(`/billing/${id}`), enabled: !isNew });
  const companies = useRefOptions("/crm/companies", (r) => r.name);
  const contacts = useRefOptions("/crm/contacts", (r) => `${r.first_name} ${r.last_name}`.trim() || r.email);

  const [f, setF] = useState({ kind: sp.get("kind") === "quote" ? "quote" : "invoice", company_id: sp.get("company") ? Number(sp.get("company")) : (null as number | null), contact_id: null as number | null, title: "", issue_date: today(), due_date: "", notes: "" });
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const [pay, setPay] = useState({ paid_on: today(), amount: "", method: "Virement" });
  useEffect(() => {
    const d = doc.data;
    if (!d) return;
    setF({ kind: d.kind, company_id: d.company_id, contact_id: d.contact_id, title: d.title, issue_date: d.issue_date, due_date: d.due_date ?? "", notes: d.notes });
    setLines(d.lines.length || d.provider === "qonto" ? d.lines.map((l: Line) => ({ description: l.description, quantity: l.quantity, unit_price: l.unit_price, vat_rate: l.vat_rate })) : [blankLine()]);
  }, [doc.data]);

  const d = doc.data;
  const fromQonto = d?.provider === "qonto";
  const editable = !fromQonto && (isNew || d?.status === "draft" || (d?.kind === "quote" && d?.status === "sent"));
  const computed = useMemo(() => totals(lines), [lines]);
  // Document Qonto : on affiche les montants de Qonto (font foi), pas un recalcul.
  const t = fromQonto && d ? { rows: [{ rate: -1, base: d.total_ht, vat: d.total_vat }], ht: d.total_ht, vat: d.total_vat, ttc: d.total_ttc } : computed;
  const body = () => ({ ...f, due_date: f.due_date || null, opportunity_id: null, lines });
  const inval = () => qc.invalidateQueries();

  const save = useMutation({
    mutationFn: () => (isNew ? api<Row>("/billing", "POST", body()) : api<Row>(`/billing/${id}`, "PUT", body())),
    onSuccess: (r) => { inval(); if (isNew) nav(`/facturation/${r.id}`, { replace: true }); },
  });
  const act = (path: string, method = "POST", b?: unknown) => ({ mutationFn: () => api<Row>(`/billing/${id}${path}`, method, b), onSuccess: (r: Row) => { inval(); if (path === "/convert") nav(`/facturation/${r.id}`); } });
  const issue = useMutation({ mutationFn: async () => { await api(`/billing/${id}`, "PUT", body()); return api<Row>(`/billing/${id}/issue`, "POST"); }, onSuccess: inval });
  const accept = useMutation(act("/status", "POST", { status: "accepted" }));
  const refuse = useMutation(act("/status", "POST", { status: "refused" }));
  const cancel = useMutation(act("/status", "POST", { status: "cancelled" }));
  const convert = useMutation(act("/convert"));
  const del = useMutation({ mutationFn: () => api(`/billing/${id}`, "DELETE"), onSuccess: () => { inval(); nav("/facturation"); } });
  const addPay = useMutation({ mutationFn: () => api(`/billing/${id}/payments`, "POST", { ...pay, amount: Number(pay.amount) }), onSuccess: () => { setPay({ ...pay, amount: "" }); inval(); } });
  const delPay = useMutation({ mutationFn: (pid: number) => api(`/billing/${id}/payments/${pid}`, "DELETE"), onSuccess: inval });
  const pdf = useMutation({ mutationFn: () => openPdf(`/billing/${id}/pdf`) });
  const [aiOpen, setAiOpen] = useState(false);
  const qontoSt = useQuery({ queryKey: ["billing-qonto"], queryFn: () => api<{ oauth_connected: boolean; ai_configured: boolean }>("/billing/qonto") });
  const push = useMutation({
    mutationFn: async () => { if (editable) await api(`/billing/${id}`, "PUT", body()); return api<Row>(`/billing/${id}/push-qonto`, "POST"); },
    onSuccess: inval,
  });

  if (!isNew && !d) return doc.error ? <ErrorMsg error={doc.error} /> : <Loading />;
  const label = f.kind === "quote" ? "Devis" : "Facture";
  const setLine = (i: number, k: keyof Line, v: string | number) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const errors = [push.error, save.error, issue.error, accept.error, refuse.error, cancel.error, convert.error, del.error, addPay.error, delPay.error, pdf.error].find(Boolean);

  return (
    <>
      <Link to="/facturation" className="text-sm text-slate-500 hover:text-brand-600">← Devis & factures</Link>
      <PageHeader title={isNew ? `Nouveau ${label.toLowerCase()}` : `${label} ${d?.number ?? "(brouillon)"}`}
        subtitle={d ? undefined : "Remplissez puis enregistrez : vous pourrez ensuite l'émettre (un numéro lui sera attribué)."}
        action={d && <div className="flex flex-wrap items-center gap-2">
          <Badge tone={d.is_overdue ? "red" : STATUS[d.status]?.[1]}>{d.is_overdue ? "En retard" : STATUS[d.status]?.[0]}</Badge>
          {fromQonto ? (d.external_url ? <a className="inline-flex items-center rounded px-3 py-2 text-sm font-medium text-brand-600 ring-1 ring-slate-200 hover:bg-slate-50" href={d.external_url} target="_blank" rel="noreferrer noopener">Ouvrir dans Qonto ↗</a> : <Button variant="ghost" busy={pdf.isPending} onClick={() => pdf.mutate()}> Aperçu PDF</Button>)
            : <Button variant="ghost" busy={pdf.isPending} onClick={() => pdf.mutate()}> PDF</Button>}
          {!fromQonto && d.kind === "quote" && <>
            <Button variant="soft" onClick={() => setAiOpen(true)} disabled={!qontoSt.data?.ai_configured} title={qontoSt.data?.ai_configured ? undefined : "Renseignez la clé API Anthropic dans Paramètres → Intégrations → Assistant IA"}>✨ Améliorer avec l'IA</Button>
            <Button busy={push.isPending} disabled={!qontoSt.data?.oauth_connected} title={qontoSt.data?.oauth_connected ? undefined : "Connectez Qonto : Paramètres → Intégrations → Banque Qonto → Se connecter avec Qonto"}
              onClick={() => confirm("Créer ce devis dans Qonto ? Il y sera « en attente de validation » (modifiable, non envoyé au client) ; ensuite il se gère dans Qonto et se met à jour ici automatiquement.") && push.mutate()}>Envoyer vers Qonto</Button>
          </>}
          {!fromQonto && <>
          {d.kind === "quote" && ["sent", "accepted"].includes(d.status) && <Button variant="soft" busy={convert.isPending} onClick={() => convert.mutate()}>→ Transformer en facture</Button>}
          {d.kind === "quote" && d.status === "sent" && <><Button variant="soft" onClick={() => accept.mutate()}>✓ Accepté</Button><Button variant="ghost" onClick={() => refuse.mutate()}>Refusé</Button></>}
          {d.kind === "invoice" && d.status === "sent" && !d.amount_paid && <Button variant="danger" onClick={() => confirm("Annuler cette facture ? Son numéro reste utilisé.") && cancel.mutate()}>Annuler la facture</Button>}
          {d.status === "draft" && <Button variant="danger" onClick={() => confirm("Supprimer ce brouillon ?") && del.mutate()}>Supprimer</Button>}
          </>}
        </div>} />
      {aiOpen && d && <AiImprove docId={d.id} current={{ title: f.title, notes: f.notes, lines }} onClose={() => setAiOpen(false)}
        onApply={(p) => { setF({ ...f, title: p.title, notes: p.notes }); setLines(p.lines.length ? p.lines : [blankLine()]); }} />}
      {d?.source_quote_id && <p className="mb-3 text-sm text-slate-500">Issue du <Link className="text-brand-600" to={`/facturation/${d.source_quote_id}`}>devis n°{d.source_quote_id}</Link></p>}
      {fromQonto && <p className="mb-4 rounded bg-slate-100 px-3 py-2 text-sm text-slate-600">Document importé de Qonto : il se crée et se modifie dans Qonto (statut, paiement…) et se met à jour ici automatiquement toutes les heures.</p>}
      {!editable && !fromQonto && <p className="mb-4 rounded bg-slate-100 px-3 py-2 text-sm text-slate-600"> Ce document est émis : il n'est plus modifiable (obligation légale). Pour corriger, annulez-le et créez-en un nouveau.</p>}
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <Card title="Informations">
            <fieldset disabled={!editable} className="grid gap-4 sm:grid-cols-2">
              {isNew && <Field label="Type"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="invoice">Facture</option><option value="quote">Devis</option></select></Field>}
              <Field label="Client *"><select value={f.company_id ?? ""} onChange={(e) => setF({ ...f, company_id: e.target.value ? Number(e.target.value) : null })}><option value="">— Choisir —</option>{companies.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
              <Field label="Contact"><select value={f.contact_id ?? ""} onChange={(e) => setF({ ...f, contact_id: e.target.value ? Number(e.target.value) : null })}><option value="">— Aucun —</option>{contacts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
              <div className="sm:col-span-2"><Field label="Objet"><input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Ex : Développement du site vitrine" /></Field></div>
              <Field label="Date d'émission"><input type="date" value={f.issue_date} onChange={(e) => setF({ ...f, issue_date: e.target.value })} /></Field>
              <Field label={f.kind === "quote" ? "Valable jusqu'au" : "Échéance de paiement"} hint="Vide = délai par défaut des paramètres"><input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
            </fieldset>
          </Card>
          <Card title="Lignes">
            <fieldset disabled={!editable}>
              <div className="space-y-3">
                {lines.map((l, i) => (
                  <div key={i} className="grid grid-cols-[1fr_70px_100px_80px_auto] items-start gap-2">
                    <textarea rows={1} placeholder="Désignation" value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} />
                    <input type="number" step="any" min="0" value={l.quantity} onChange={(e) => setLine(i, "quantity", Number(e.target.value))} title="Quantité" />
                    <input type="number" step="0.01" value={l.unit_price} onChange={(e) => setLine(i, "unit_price", Number(e.target.value))} title="Prix unitaire HT" />
                    <select value={l.vat_rate} onChange={(e) => setLine(i, "vat_rate", Number(e.target.value))} title="TVA">{[20, 10, 5.5, 2.1, 0].map((r) => <option key={r} value={r}>{r} %</option>)}</select>
                    <button type="button" className="px-2 pt-2 text-red-500 disabled:opacity-30" disabled={lines.length === 1} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>✕</button>
                  </div>
                ))}
              </div>
              {fromQonto && !lines.length && <p className="text-sm text-slate-400">Détail des lignes non fourni par Qonto : voir le document dans Qonto.</p>}
              {!fromQonto && <><p className="mt-2 text-xs text-slate-400">Colonnes : désignation · quantité · prix unitaire HT · TVA</p>
              <Button type="button" variant="soft" className="mt-3" onClick={() => setLines((ls) => [...ls, blankLine()])}>+ Ajouter une ligne</Button></>}
            </fieldset>
            <div className="mt-5 ml-auto max-w-xs space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-slate-500">Total HT</span><span>{fmtMoney(t.ht)}</span></div>
              {t.rows.map((r) => <div key={r.rate} className="flex justify-between text-slate-500"><span>{r.rate < 0 ? "TVA" : `TVA ${r.rate} %`}</span><span>{fmtMoney(r.vat)}</span></div>)}
              <div className="flex justify-between border-t pt-1 text-base font-bold"><span>Total TTC</span><span>{fmtMoney(t.ttc)}</span></div>
            </div>
          </Card>
          <Card title="Notes / conditions"><fieldset disabled={!editable}><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Conditions particulières, RIB, mentions… (affiché sur le PDF)" /></fieldset></Card>
          <ErrorMsg error={errors} />
          {editable && (
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="ghost" busy={save.isPending} onClick={() => save.mutate()}> Enregistrer le brouillon</Button>
              {!isNew && d?.status === "draft" && <Button busy={issue.isPending} onClick={() => confirm(`Émettre ce ${label.toLowerCase()} ? Un numéro définitif lui sera attribué et il ne sera plus modifiable.`) && issue.mutate()}> Émettre</Button>}
            </div>
          )}
        </div>
        <div className="space-y-6">
          {d && d.kind === "invoice" && ["sent", "paid"].includes(d.status) && (
            <Card title="Paiements">
              <p className="mb-3 text-sm">Reste à payer : <b className={d.remaining ? "text-amber-600" : "text-emerald-800"}>{fmtMoney(d.remaining)}</b></p>
              <ul className="mb-3 space-y-1 text-sm">{d.payments.map((p: Row) => <li key={p.id} className="flex justify-between"><span>{fmtDate(p.paid_on)} · {p.method}</span><span>{fmtMoney(p.amount)} {!fromQonto && <button className="ml-1 text-xs text-red-500" onClick={() => delPay.mutate(p.id)}>✕</button>}</span></li>)}</ul>
              {d.remaining > 0 && !fromQonto && (
                <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); addPay.mutate(); }}>
                  <input type="date" value={pay.paid_on} onChange={(e) => setPay({ ...pay, paid_on: e.target.value })} />
                  <input type="number" step="0.01" required placeholder={`Montant (max ${d.remaining})`} value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} />
                  <select value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>{["Virement", "Carte bancaire", "Chèque", "Espèces", "Prélèvement"].map((m) => <option key={m}>{m}</option>)}</select>
                  <Button type="submit" busy={addPay.isPending} className="w-full">Enregistrer le paiement</Button>
                  <Button type="button" variant="ghost" className="w-full" onClick={() => setPay({ ...pay, amount: String(d.remaining) })}>Solde complet</Button>
                </form>
              )}
            </Card>
          )}
          {!fromQonto && <Card title="Aide"><p className="text-xs leading-relaxed text-slate-500">Le numéro est attribué à l'émission, sans trou, par type et par année (DEV-2026-0001, FAC-2026-0001). Les informations de votre société (SIRET, IBAN, mentions) sont à renseigner dans <b>Paramètres → Ma société</b> : elles figurent sur le PDF.</p></Card>}
        </div>
      </div>
    </>
  );
}
