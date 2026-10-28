import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Project, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, StatusDot, fmtDateTime } from "../ui";

export const emptyProject = {
  name: "", url: "", description: "", environment: "prod", repo_url: "", monitoring_tools: "", notes: "",
  monitoring_enabled: true, public_status: false, check_interval_min: 5, expected_status: null as number | null,
};
export type ProjectForm = typeof emptyProject;

export function ProjectFormModal({ initial, id, onClose }: { initial: ProjectForm; id?: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState<ProjectForm>(initial);
  const set = <K extends keyof ProjectForm>(k: K, v: ProjectForm[K]) => setF((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => (id ? api(`/projects/${id}`, "PUT", f) : api("/projects", "POST", f)),
    onSuccess: () => { qc.invalidateQueries(); onClose(); },
  });
  return (
    <Modal title={id ? "Modifier le projet" : "Nouveau projet"} onClose={onClose} wide>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid gap-4 sm:grid-cols-2">
        <Field label="Nom *"><input required value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Formasyl" /></Field>
        <Field label="Adresse du site *"><input required value={f.url} onChange={(e) => set("url", e.target.value)} placeholder="https://formasyl.org" /></Field>
        <Field label="Environnement">
          <select value={f.environment} onChange={(e) => set("environment", e.target.value)}>
            <option value="prod">Production</option><option value="staging">Pré-production</option><option value="dev">Développement</option>
          </select>
        </Field>
        <Field label="Dépôt de code" hint="Lien GitHub (facultatif)"><input value={f.repo_url} onChange={(e) => set("repo_url", e.target.value)} /></Field>
        <div className="sm:col-span-2"><Field label="Outils de monitoring utilisés" hint="Ex : Uptime Kuma, CrowdSec, Cloudflare…"><input value={f.monitoring_tools} onChange={(e) => set("monitoring_tools", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><Field label="Description"><textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field></div>
        <Field label="Vérifier toutes les (minutes)"><input type="number" min={1} max={1440} value={f.check_interval_min} onChange={(e) => set("check_interval_min", Number(e.target.value))} /></Field>
        <Field label="Code HTTP attendu" hint="Laisser vide : tout code < 500 = en ligne">
          <input type="number" value={f.expected_status ?? ""} onChange={(e) => set("expected_status", e.target.value ? Number(e.target.value) : null)} />
        </Field>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={f.monitoring_enabled} onChange={(e) => set("monitoring_enabled", e.target.checked)} /> Surveiller ce site automatiquement
        </label>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input type="checkbox" checked={f.public_status} onChange={(e) => set("public_status", e.target.checked)} /> Afficher sur la page de statut publique (<code>/statut</code> : seulement le nom et l'état)
        </label>
        <div className="sm:col-span-2"><ErrorMsg error={save.error} /></div>
        <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
          <Button type="button" variant="ghost" onClick={onClose}>Annuler</Button>
          <Button type="submit" busy={save.isPending}>Enregistrer</Button>
        </div>
      </form>
    </Modal>
  );
}

const ENV: Record<string, string> = { prod: "Production", staging: "Pré-prod", dev: "Dev" };

export default function Projects() {
  const [adding, setAdding] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects"), refetchInterval: 30_000 });
  return (
    <>
      <PageHeader title="Projets & serveurs" subtitle="Tous vos sites, leurs serveurs, leurs technologies et leur état en direct."
        action={<Button onClick={() => setAdding(true)}>+ Ajouter un projet</Button>} />
      {isLoading || !data ? <Loading /> : data.length === 0 ? <Empty>Aucun projet pour l'instant.</Empty> : (
        <div className="grid gap-4 md:grid-cols-2">
          {data.map((p) => (
            <Link key={p.id} to={`/projets/${p.id}`}>
              <Card className="h-full transition hover:border-brand-500">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold text-slate-900">{p.name}</h3>
                    <p className="truncate text-sm text-brand-600">{p.url}</p>
                  </div>
                  <Badge tone={p.environment === "prod" ? "blue" : "slate"}>{ENV[p.environment]}</Badge>
                </div>
                <div className="mt-4 flex items-center justify-between">
                  <StatusDot status={p.status} />
                  <span className="text-xs text-slate-400">{p.last_checked_at ? `Vérifié ${fmtDateTime(p.last_checked_at)}` : ""}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                  <Badge>{p.servers.length} serveur{p.servers.length > 1 ? "s" : ""}</Badge>
                  <Badge>{p.technologies.length} techno{p.technologies.length > 1 ? "s" : ""}</Badge>
                  {p.open_vulnerabilities > 0 && <Badge tone="red">{p.open_vulnerabilities} faille(s)</Badge>}
                  {p.missing_headers.length > 0 && <Badge tone="amber">{p.missing_headers.length} en-tête(s) sécu manquant(s)</Badge>}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
      {adding && <ProjectFormModal initial={emptyProject} onClose={() => setAdding(false)} />}
    </>
  );
}
