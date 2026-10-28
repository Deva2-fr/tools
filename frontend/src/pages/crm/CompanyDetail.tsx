import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Row, api } from "../../api";
import { FormModal, defaults } from "../../components";
import { Badge, Button, Card, Empty, ErrorMsg, Loading, PageHeader, fmtDate, fmtDateTime, fmtMoney } from "../../ui";
import { CompanyLookup } from "./CompanyLookup";
import { STAGES, companyFields, contactFields, kindLabel, kindTone, oppFields, taskFields } from "./shared";

interface Overview {
  company: Row; contacts: Row[]; opportunities: Row[]; tasks: Row[]; activities: Row[]; documents: Row[]; files: Row[];
  mails: { id: number; subject: string; sender: string; received_at: string; tag: string; web_link: string }[];
  money_visible: boolean; invoiced: number | null; outstanding: number | null;
}
type Modal = null | "company" | "contact" | "opp" | "task";
const ACT: Record<string, string> = { note: "", call: "", meeting: "", email: "" };
const DOC_STATUS: Record<string, string> = { draft: "Brouillon", sent: "Émis", accepted: "Accepté", refused: "Refusé", paid: "Payée", cancelled: "Annulée" };

export default function CompanyDetail() {
  const { id } = useParams();
  const cid = Number(id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const [modal, setModal] = useState<Modal>(null);
  const [act, setAct] = useState({ kind: "note", subject: "", body: "" });
  const ov = useQuery({ queryKey: ["company", cid], queryFn: () => api<Overview>(`/crm/companies/${cid}/overview`) });
  const inval = () => qc.invalidateQueries();
  const closeAnd = () => { inval(); setModal(null); };
  const base = { company_id: cid };
  const post = (path: string) => ({ mutationFn: (b: Record<string, unknown>) => api(path, "POST", b), onSuccess: closeAnd });
  const saveCompany = useMutation({ mutationFn: (b: Record<string, unknown>) => api(`/crm/companies/${cid}`, "PUT", b), onSuccess: closeAnd });
  const addContact = useMutation(post("/crm/contacts"));
  const addOpp = useMutation(post("/crm/opportunities"));
  const addTask = useMutation(post("/crm/tasks"));
  const addAct = useMutation({ mutationFn: () => api("/crm/activities", "POST", { ...act, company_id: cid }), onSuccess: () => { setAct({ kind: "note", subject: "", body: "" }); inval(); } });
  const delAct = useMutation({ mutationFn: (i: number) => api(`/crm/activities/${i}`, "DELETE"), onSuccess: inval });
  const toggle = useMutation({ mutationFn: (i: number) => api(`/crm/tasks/${i}/toggle`, "POST"), onSuccess: inval });
  const delCompany = useMutation({ mutationFn: () => api(`/crm/companies/${cid}`, "DELETE"), onSuccess: () => { inval(); nav("/crm/societes"); } });

  if (!ov.data) return ov.error ? <ErrorMsg error={ov.error} /> : <Loading />;
  const d = ov.data;
  const c = d.company;
  return (
    <>
      <Link to="/crm/societes" className="text-sm text-slate-500 hover:text-brand-600">← Toutes les sociétés</Link>
      <PageHeader title={c.name} subtitle={[c.sector, [c.postal_code, c.city].filter(Boolean).join(" ")].filter(Boolean).join(" · ") || undefined}
        action={<div className="flex flex-wrap gap-2">
          {d.money_visible && <Button variant="soft" onClick={() => nav(`/facturation/nouveau?kind=quote&company=${cid}`)}>+ Devis</Button>}
          {d.money_visible && <Button variant="soft" onClick={() => nav(`/facturation/nouveau?kind=invoice&company=${cid}`)}>+ Facture</Button>}
          <Button variant="ghost" onClick={() => setModal("company")}>Modifier</Button>
          <Button variant="danger" onClick={() => confirm(`Supprimer « ${c.name} » ? Ses contacts seront conservés.`) && delCompany.mutate()}>Supprimer</Button>
        </div>} />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Card><p className="text-xs text-slate-400">Type</p><div className="mt-1"><Badge tone={kindTone(c.kind)}>{kindLabel(c.kind)}</Badge></div></Card>
        <Card><p className="text-xs text-slate-400">Contact</p><p className="mt-1 truncate text-sm">{c.email || c.phone || "—"}</p></Card>
        {d.money_visible ? <>
          <Card><p className="text-xs text-slate-400">Facturé (émis)</p><p className="mt-1 text-lg font-bold">{fmtMoney(d.invoiced)}</p></Card>
          <Card><p className="text-xs text-slate-400">Reste à encaisser</p><p className={`mt-1 text-lg font-bold ${(d.outstanding ?? 0) > 0 ? "text-amber-600" : ""}`}>{fmtMoney(d.outstanding)}</p></Card>
        </> : <><Card><p className="text-xs text-slate-400">SIRET</p><p className="mt-1 text-sm">{c.siret || "—"}</p></Card><Card><p className="text-xs text-slate-400">Site</p><p className="mt-1 truncate text-sm">{c.website || "—"}</p></Card></>}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Contacts" action={<Button variant="soft" onClick={() => setModal("contact")}>+ Contact</Button>}>
          {!d.contacts.length ? <Empty>Aucun contact.</Empty> : <ul className="divide-y divide-slate-100 text-sm">{d.contacts.map((p) => (
            <li key={p.id} className="py-2.5"><b>{`${p.first_name} ${p.last_name}`.trim()}</b> <span className="text-slate-400">{p.job_title}</span>
              <p className="text-xs text-slate-500">{p.email} {p.phone && `· ${p.phone}`}</p></li>))}</ul>}
        </Card>
        <Card title="Affaires en cours" action={<Button variant="soft" onClick={() => setModal("opp")}>+ Affaire</Button>}>
          {!d.opportunities.length ? <Empty>Aucune affaire.</Empty> : <ul className="divide-y divide-slate-100 text-sm">{d.opportunities.map((o) => (
            <li key={o.id} className="flex items-center justify-between py-2.5"><span>{o.title}</span><span className="flex items-center gap-2"><b>{fmtMoney(o.amount)}</b><Badge tone={o.stage === "won" ? "green" : o.stage === "lost" ? "red" : "blue"}>{STAGES.find((s) => s.key === o.stage)?.label}</Badge></span></li>))}</ul>}
        </Card>
        <Card title="Tâches à faire" action={<Button variant="soft" onClick={() => setModal("task")}>+ Tâche</Button>}>
          {!d.tasks.length ? <Empty>Aucune tâche.</Empty> : <ul className="divide-y divide-slate-100 text-sm">{d.tasks.map((t) => (
            <li key={t.id} className="flex items-center gap-3 py-2.5"><input type="checkbox" onChange={() => toggle.mutate(t.id)} /><span className="flex-1">{t.title}</span>{t.due_date && <Badge>{fmtDate(t.due_date)}</Badge>}</li>))}</ul>}
        </Card>
        {d.money_visible && (
          <Card title="Devis & factures">
            {!d.documents.length ? <Empty>Aucun document.</Empty> : <ul className="divide-y divide-slate-100 text-sm">{d.documents.map((x) => (
              <li key={x.id} className="flex items-center justify-between py-2.5"><Link className="text-brand-600" to={`/facturation/${x.id}`}>{x.number ?? "Brouillon"} · {x.kind === "quote" ? "Devis" : "Facture"}</Link>
                <span className="flex items-center gap-2"><b>{fmtMoney(x.total_ttc)}</b><Badge>{DOC_STATUS[x.status] ?? x.status}</Badge></span></li>))}</ul>}
          </Card>
        )}
        <Card title="Journal d'activité" className="lg:col-span-2">
          <form className="mb-4 grid gap-3 sm:grid-cols-[140px_1fr_auto]" onSubmit={(e) => { e.preventDefault(); if (act.subject.trim()) addAct.mutate(); }}>
            <select value={act.kind} onChange={(e) => setAct({ ...act, kind: e.target.value })}><option value="note"> Note</option><option value="call"> Appel</option><option value="meeting"> Rendez-vous</option><option value="email"> E-mail</option></select>
            <input placeholder="Ce qui s'est passé…" value={act.subject} onChange={(e) => setAct({ ...act, subject: e.target.value })} />
            <Button type="submit" busy={addAct.isPending}>Ajouter</Button>
          </form>
          <ul className="space-y-3 text-sm">
            {d.activities.map((a) => (
              <li key={a.id} className="flex gap-3"><span>{ACT[a.kind] ?? "•"}</span>
                <div className="flex-1"><p>{a.subject}</p><p className="text-xs text-slate-400">{fmtDateTime(a.created_at)} · {a.created_by}</p></div>
                <button className="text-xs text-slate-300 hover:text-red-600" onClick={() => delAct.mutate(a.id)}>✕</button></li>))}
            {!d.activities.length && <Empty>Aucune activité enregistrée.</Empty>}
          </ul>
        </Card>
        <Card title="Mails Outlook liés" className="lg:col-span-2">
          {!d.mails.length ? <Empty>Aucun mail reçu de cette société (ou boîte Outlook non connectée).</Empty> : <ul className="divide-y divide-slate-100 text-sm">{d.mails.map((m) => (
            <li key={m.id} className="flex items-center justify-between py-2.5"><span><b>{m.subject || "(sans objet)"}</b> <span className="text-slate-400">· {m.sender} · {fmtDateTime(m.received_at)}</span></span>
              <span className="flex items-center gap-3">{(m.tag === "a_repondre" || m.tag === "urgent") && <Badge tone="amber">À répondre</Badge>}{m.web_link && <a className="text-xs text-brand-600" href={m.web_link} target="_blank" rel="noreferrer noopener">Ouvrir ↗</a>}</span></li>))}</ul>}
        </Card>
        {!!d.files.length && <Card title="Documents" className="lg:col-span-2"><ul className="text-sm">{d.files.map((f) => <li key={f.id}> {f.name} <Badge>{f.category}</Badge></li>)}</ul></Card>}
      </div>
      {modal === "company" && <FormModal title="Modifier la société" fields={companyFields} initial={c} onClose={() => setModal(null)} onSubmit={(b) => saveCompany.mutate(b)} busy={saveCompany.isPending} error={saveCompany.error} top={(patch) => <CompanyLookup onPick={patch} syncName={false} />} />}
      {modal === "contact" && <FormModal title="Nouveau contact" fields={contactFields} initial={defaults(contactFields, base)} onClose={() => setModal(null)} onSubmit={(b) => addContact.mutate(b)} busy={addContact.isPending} error={addContact.error} />}
      {modal === "opp" && <FormModal title="Nouvelle affaire" fields={oppFields} initial={defaults(oppFields, { ...base, amount: 0, probability: 10, stage: "prospect" })} onClose={() => setModal(null)} onSubmit={(b) => addOpp.mutate(b)} busy={addOpp.isPending} error={addOpp.error} />}
      {modal === "task" && <FormModal title="Nouvelle tâche" fields={taskFields} initial={defaults(taskFields, base)} onClose={() => setModal(null)} onSubmit={(b) => addTask.mutate(b)} busy={addTask.isPending} error={addTask.error} />}
    </>
  );
}
