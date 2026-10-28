import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Row, api } from "../api";
import { ResourcePage } from "../components";
import { Badge, Button, Modal, fmtDate } from "../ui";

const ONBOARDING = ["Créer le compte e-mail", "Créer le compte dans le Hub", "Donner accès à GitHub / aux dépôts", "Remettre le matériel", "Ajouter au gestionnaire de mots de passe", "Présenter l'équipe et les outils", "Signer le contrat et collecter les pièces administratives"];
const OFFBOARDING = ["Récupérer le matériel", "Désactiver le compte e-mail", "Retirer les accès GitHub / serveurs", "Changer les mots de passe partagés", "Supprimer le compte du Hub", "Solde de tout compte et attestations"];

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
      <ResourcePage title="Collaborateurs" subtitle="Fiches de l'équipe. L'e-mail relie le collaborateur à son compte (temps passé)." endpoint="/employees" newLabel="Nouveau collaborateur" exportName="equipe"
        initial={{ contract: "CDI", daily_cost: 0 }}
        fields={[
          { name: "name", label: "Nom complet", required: true }, { name: "email", label: "E-mail (identique à son compte Hub)", type: "email" },
          { name: "job_title", label: "Poste" }, { name: "contract", label: "Contrat", type: "select", options: [["CDI", "CDI"], ["CDD", "CDD"], ["Freelance", "Freelance"], ["Alternance", "Alternance"], ["Stage", "Stage"], ["Associé", "Associé"]] },
          { name: "start_date", label: "Date d'arrivée", type: "date" }, { name: "end_date", label: "Date de départ", type: "date" },
          { name: "daily_cost", label: "Coût journalier chargé (€)", type: "number", hint: "Sert au calcul de rentabilité" },
          { name: "notes", label: "Notes", type: "textarea" },
        ]}
        columns={[{ label: "Nom", render: (r) => <span className="font-medium">{r.name}</span> }, { label: "Poste", render: (r) => r.job_title || "—" }, { label: "Contrat", render: (r) => r.contract }, { label: "E-mail", render: (r) => r.email || <Badge tone="amber">à renseigner</Badge> }, { label: "Arrivée", render: (r) => fmtDate(r.start_date) }]}
        rowActions={(r) => <button className="text-brand-600" onClick={() => setCl(r)}>Check-lists</button>} />
      {cl && <Checklist emp={cl} onClose={() => setCl(null)} />}
    </>
  );
}

