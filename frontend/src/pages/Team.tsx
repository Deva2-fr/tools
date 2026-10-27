import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, User, api, isManager } from "../api";
import { ResourcePage, useRefOptions } from "../components";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDate } from "../ui";

const LEAVE: Record<string, string> = { paid: "Congés payés", rtt: "RTT", sick: "Maladie", unpaid: "Sans solde" };
const LSTATUS: Record<string, [string, "amber" | "green" | "red"]> = { pending: ["En attente", "amber"], approved: ["Validé", "green"], refused: ["Refusé", "red"] };
const ONBOARDING = ["Créer le compte e-mail", "Créer le compte dans le Hub", "Donner accès à GitHub / aux dépôts", "Remettre le matériel", "Ajouter au gestionnaire de mots de passe", "Présenter l'équipe et les outils", "Signer le contrat et collecter les pièces administratives"];
const OFFBOARDING = ["Récupérer le matériel", "Désactiver le compte e-mail", "Retirer les accès GitHub / serveurs", "Changer les mots de passe partagés", "Supprimer le compte du Hub", "Solde de tout compte et attestations"];

export function Leaves({ user }: { user: User }) {
  const qc = useQueryClient();
  const manager = isManager(user);
  const employees = useRefOptions(manager ? "/employees" : undefined, (r) => r.name);
  const [f, setF] = useState({ employee_id: null as number | null, start_date: "", end_date: "", kind: "paid", note: "" });
  const list = useQuery({ queryKey: ["leaves"], queryFn: () => api<Row[]>("/leaves") });
  const cal = useQuery({ queryKey: ["leave-cal"], queryFn: () => api<Row[]>("/leaves/calendar") });
  const bal = useQuery({ queryKey: ["leave-bal"], queryFn: () => api<Row[]>("/leaves/balances"), enabled: manager });
  const inval = () => qc.invalidateQueries();
  const req = useMutation({ mutationFn: () => api("/leaves", "POST", { ...f, employee_id: manager ? f.employee_id : null }), onSuccess: () => { setF({ ...f, start_date: "", end_date: "", note: "" }); inval(); } });
  const decide = useMutation({ mutationFn: ({ id, status }: { id: number; status: string }) => api(`/leaves/${id}/decide`, "POST", { status }), onSuccess: inval });
  const del = useMutation({ mutationFn: (id: number) => api(`/leaves/${id}`, "DELETE"), onSuccess: inval });
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Poser des congés">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); req.mutate(); }}>
          {manager && <Field label="Collaborateur"><select required value={f.employee_id ?? ""} onChange={(e) => setF({ ...f, employee_id: e.target.value ? Number(e.target.value) : null })}><option value="">— Choisir —</option>{employees.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>}
          <div className="grid grid-cols-2 gap-3"><Field label="Du"><input type="date" required value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value, end_date: f.end_date || e.target.value })} /></Field><Field label="Au (inclus)"><input type="date" required value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></Field></div>
          <Field label="Type"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{Object.entries(LEAVE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Commentaire"><input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
          <ErrorMsg error={req.error} />
          <Button type="submit" busy={req.isPending}>Envoyer la demande</Button>
          <p className="text-xs text-slate-400">Les week-ends sont exclus automatiquement du décompte. Votre fiche collaborateur est retrouvée grâce à votre e-mail.</p>
        </form>
      </Card>
      <Card title="Qui est absent ?">
        {!cal.data?.length ? <Empty>Aucune absence à venir.</Empty> : <ul className="divide-y divide-slate-100 text-sm">{cal.data.map((c, i) => <li key={i} className="flex justify-between py-2"><b>{c.employee}</b><span className="text-slate-500">{fmtDate(c.start_date)} → {fmtDate(c.end_date)}</span></li>)}</ul>}
      </Card>
      <Card title={manager ? "Toutes les demandes" : "Mes demandes"} className="lg:col-span-2">
        {list.isLoading ? <Loading /> : !list.data?.length ? <Empty>Aucune demande.</Empty> : <ul className="divide-y divide-slate-100 text-sm">{list.data.map((l) => (
          <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <span><b>{l.employee}</b> · {LEAVE[l.kind]} · {fmtDate(l.start_date)} → {fmtDate(l.end_date)} <span className="text-slate-400">({l.days} j)</span> {l.note && <span className="text-slate-400">— {l.note}</span>}</span>
            <span className="flex items-center gap-2"><Badge tone={LSTATUS[l.status][1]}>{LSTATUS[l.status][0]}</Badge>
              {manager && l.status === "pending" && <><Button variant="soft" onClick={() => decide.mutate({ id: l.id, status: "approved" })}>Valider</Button><Button variant="ghost" onClick={() => decide.mutate({ id: l.id, status: "refused" })}>Refuser</Button></>}
              {(manager || l.status === "pending") && <button className="text-xs text-red-500" onClick={() => confirm("Supprimer cette demande ?") && del.mutate(l.id)}>✕</button>}</span></li>))}</ul>}
        <ErrorMsg error={decide.error} />
      </Card>
      {manager && bal.data && <Card title={`Soldes de congés payés ${new Date().getFullYear()}`} className="lg:col-span-2"><div className="grid gap-3 sm:grid-cols-3">{bal.data.map((b) => <div key={b.employee_id} className="rounded-lg border border-slate-200 p-3 text-sm"><b>{b.name}</b><p className="text-slate-500">{b.used} pris / {b.allowance} · <b className={b.left < 0 ? "text-red-600" : "text-emerald-600"}>{b.left} restants</b></p></div>)}</div></Card>}
    </div>
  );
}

function Checklist({ emp, onClose }: { emp: Row; onClose: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("onboarding");
  const items = useQuery({ queryKey: ["checklist", emp.id], queryFn: () => api<Row[]>(`/checklist?employee_id=${emp.id}`) });
  const inval = () => qc.invalidateQueries({ queryKey: ["checklist", emp.id] });
  const add = useMutation({ mutationFn: (b: { title: string; kind: string }) => api("/checklist", "POST", { employee_id: emp.id, done: false, ...b }), onSuccess: () => { setTitle(""); inval(); } });
  const toggle = useMutation({ mutationFn: (it: Row) => api(`/checklist/${it.id}`, "PUT", { employee_id: it.employee_id, kind: it.kind, title: it.title, done: !it.done }), onSuccess: inval });
  const del = useMutation({ mutationFn: (id: number) => api(`/checklist/${id}`, "DELETE"), onSuccess: inval });
  const fill = async (list: string[], k: string) => { for (const t of list) await api("/checklist", "POST", { employee_id: emp.id, kind: k, title: t, done: false }); inval(); };
  return (
    <Modal title={`Check-lists – ${emp.name}`} onClose={onClose} wide>
      <div className="mb-4 flex flex-wrap gap-2"><Button variant="soft" onClick={() => fill(ONBOARDING, "onboarding")}>+ Modèle arrivée</Button><Button variant="soft" onClick={() => fill(OFFBOARDING, "offboarding")}>+ Modèle départ</Button></div>
      {(["onboarding", "offboarding"] as const).map((k) => { const rows = (items.data ?? []).filter((i) => i.kind === k); return rows.length ? (
        <div key={k} className="mb-4"><p className="mb-1 text-xs font-semibold uppercase text-slate-400">{k === "onboarding" ? "Arrivée" : "Départ"} ({rows.filter((r) => r.done).length}/{rows.length})</p>
          <ul className="space-y-1 text-sm">{rows.map((it) => <li key={it.id} className="flex items-center gap-2"><input type="checkbox" checked={it.done} onChange={() => toggle.mutate(it)} /><span className={it.done ? "text-slate-400 line-through" : ""}>{it.title}</span><button className="ml-auto text-xs text-red-500" onClick={() => del.mutate(it.id)}>✕</button></li>)}</ul></div>) : null; })}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) add.mutate({ title, kind }); }}>
        <select className="!w-32" value={kind} onChange={(e) => setKind(e.target.value)}><option value="onboarding">Arrivée</option><option value="offboarding">Départ</option></select>
        <input placeholder="Nouvelle étape…" value={title} onChange={(e) => setTitle(e.target.value)} /><Button type="submit">Ajouter</Button></form>
    </Modal>
  );
}

export function Employees() {
  const [cl, setCl] = useState<Row | null>(null);
  return (
    <>
      <ResourcePage title="Collaborateurs" subtitle="Fiches de l'équipe. L'e-mail relie le collaborateur à son compte (congés, temps passé)." endpoint="/employees" newLabel="Nouveau collaborateur" exportName="equipe"
        initial={{ contract: "CDI", leave_days_per_year: 25, daily_cost: 0 }}
        fields={[
          { name: "name", label: "Nom complet", required: true }, { name: "email", label: "E-mail (identique à son compte Hub)", type: "email" },
          { name: "job_title", label: "Poste" }, { name: "contract", label: "Contrat", type: "select", options: [["CDI", "CDI"], ["CDD", "CDD"], ["Freelance", "Freelance"], ["Alternance", "Alternance"], ["Stage", "Stage"], ["Associé", "Associé"]] },
          { name: "start_date", label: "Date d'arrivée", type: "date" }, { name: "end_date", label: "Date de départ", type: "date" },
          { name: "daily_cost", label: "Coût journalier chargé (€)", type: "number", hint: "Sert au calcul de rentabilité" }, { name: "leave_days_per_year", label: "Congés payés / an", type: "number" },
          { name: "notes", label: "Notes", type: "textarea" },
        ]}
        columns={[{ label: "Nom", render: (r) => <span className="font-medium">{r.name}</span> }, { label: "Poste", render: (r) => r.job_title || "—" }, { label: "Contrat", render: (r) => r.contract }, { label: "E-mail", render: (r) => r.email || <Badge tone="amber">à renseigner</Badge> }, { label: "Arrivée", render: (r) => fmtDate(r.start_date) }]}
        rowActions={(r) => <button className="text-brand-600" onClick={() => setCl(r)}>Check-lists</button>} />
      {cl && <Checklist emp={cl} onClose={() => setCl(null)} />}
    </>
  );
}

export default function Team({ user }: { user: User }) {
  return (<><PageHeader title="Équipe & congés" subtitle="Posez vos congés, voyez qui est absent." /><Leaves user={user} /></>);
}
