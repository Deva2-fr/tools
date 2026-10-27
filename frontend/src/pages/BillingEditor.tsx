import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Row, api, openPdf } from "../api";
import { useRefOptions } from "../components";
import { Badge, Button, Card, ErrorMsg, Field, Loading, PageHeader, fmtDate, fmtMoney } from "../ui";
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
    setLines(d.lines.length ? d.lines.map((l: Line) => ({ description: l.description, quantity: l.quantity, unit_price: l.unit_price, vat_rate: l.vat_rate })) : [blankLine()]);
  }, [doc.data]);

  const d = doc.data;
  const editable = isNew || d?.status === "draft" || (d?.kind === "quote" && d?.status === "sent");
  const t = useMemo(() => totals(lines), [lines]);
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

  if (!isNew && !d) return doc.error ? <ErrorMsg error={doc.error} /> : <Loading />;
  const label = f.kind === "quote" ? "Devis" : "Facture";
  const setLine = (i: number, k: keyof Line, v: string | number) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const errors = [save.error, issue.error, accept.error, refuse.error, cancel.error, convert.error, del.error, addPay.error, delPay.error, pdf.error].find(Boolean);

  return (
    <>
      <Link to="/facturation" className="text-sm text-slate-500 hover:text-brand-600">← Devis & factures</Link>
      <PageHeader title={isNew ? `Nouveau ${label.toLowerCase()}` : `${label} ${d?.number ?? "(brouillon)"}`}
        subtitle={d ? undefined : "Remplissez puis enregistrez : vous pourrez ensuite l'émettre (un numéro lui sera attribué)."}
        action={d && <div className="flex flex-wrap items-center gap-2">
          <Badge tone={d.is_overdue ? "red" : STATUS[d.status]?.[1]}>{d.is_overdue ? "En retard" : STATUS[d.status]?.[0]}</Badge>
          <Button variant="ghost" busy={pdf.isPending} onClick={() => pdf.mutate()}>📄 PDF</Button>
          {d.kind === "quote" && ["sent", "accepted"].includes(d.status) && <Button variant="soft" busy={convert.isPending} onClick={() => convert.mutate()}>→ Transformer en facture</Button>}
          {d.kind === "quote" && d.status === "sent" && <><Button variant="soft" onClick={() => accept.mutate()}>✔ Accepté</Button><Button variant="ghost" onClick={() => refuse.mutate()}>Refusé</Button></>}
          {d.kind === "invoice" && d.status === "sent" && !d.amount_paid && <Button variant="danger" onClick={() => confirm("Annuler cette facture ? Son numéro reste utilisé.") && cancel.mutate()}>Annuler la facture</Button>}
          {d.status === "draft" && <Button variant="danger" onClick={() => confirm("Supprimer ce brouillon ?") && del.mutate()}>Supprimer</Button>}
        </div>} />
      {d?.source_quote_id && <p className="mb-3 text-sm text-slate-500">Issue du <Link className="text-brand-600" to={`/facturation/${d.source_quote_id}`}>devis n°{d.source_quote_id}</Link></p>}
      {!editable && <p className="mb-4 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-600">🔒 Ce document est émis : il n'est plus modifiable (obligation légale). Pour corriger, annulez-le et créez-en un nouveau.</p>}
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
              <p className="mt-2 text-xs text-slate-400">Colonnes : désignation · quantité · prix unitaire HT · TVA</p>
              <Button type="button" variant="soft" className="mt-3" onClick={() => setLines((ls) => [...ls, blankLine()])}>+ Ajouter une ligne</Button>
            </fieldset>
            <div className="mt-5 ml-auto max-w-xs space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-slate-500">Total HT</span><span>{fmtMoney(t.ht)}</span></div>
              {t.rows.map((r) => <div key={r.rate} className="flex justify-between text-slate-500"><span>TVA {r.rate} %</span><span>{fmtMoney(r.vat)}</span></div>)}
              <div className="flex justify-between border-t pt-1 text-base font-bold"><span>Total TTC</span><span>{fmtMoney(t.ttc)}</span></div>
            </div>
          </Card>
          <Card title="Notes / conditions"><fieldset disabled={!editable}><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Conditions particulières, RIB, mentions… (affiché sur le PDF)" /></fieldset></Card>
          <ErrorMsg error={errors} />
          {editable && (
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="ghost" busy={save.isPending} onClick={() => save.mutate()}>💾 Enregistrer le brouillon</Button>
              {!isNew && d?.status === "draft" && <Button busy={issue.isPending} onClick={() => confirm(`Émettre ce ${label.toLowerCase()} ? Un numéro définitif lui sera attribué et il ne sera plus modifiable.`) && issue.mutate()}>✅ Émettre</Button>}
            </div>
          )}
        </div>
        <div className="space-y-6">
          {d && d.kind === "invoice" && ["sent", "paid"].includes(d.status) && (
            <Card title="Paiements">
              <p className="mb-3 text-sm">Reste à payer : <b className={d.remaining ? "text-amber-600" : "text-emerald-600"}>{fmtMoney(d.remaining)}</b></p>
              <ul className="mb-3 space-y-1 text-sm">{d.payments.map((p: Row) => <li key={p.id} className="flex justify-between"><span>{fmtDate(p.paid_on)} · {p.method}</span><span>{fmtMoney(p.amount)} <button className="ml-1 text-xs text-red-500" onClick={() => delPay.mutate(p.id)}>✕</button></span></li>)}</ul>
              {d.remaining > 0 && (
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
          <Card title="Aide"><p className="text-xs leading-relaxed text-slate-500">Le numéro est attribué à l'émission, sans trou, par type et par année (DEV-2026-0001, FAC-2026-0001). Les informations de votre société (SIRET, IBAN, mentions) sont à renseigner dans <b>Paramètres → Ma société</b> : elles figurent sur le PDF.</p></Card>
        </div>
      </div>
    </>
  );
}
