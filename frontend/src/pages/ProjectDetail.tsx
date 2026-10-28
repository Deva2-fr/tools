import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Check, Project, Server, Tech, Vuln, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, StatusDot, fmtDate, fmtDateTime } from "../ui";
import { ProjectFormModal } from "./Projects";

const emptyServer = { label: "", provider: "", hostname: "", ip: "", os: "", location: "", specs: "", access_info: "", notes: "" };
const emptyTech = { name: "", version: "", category: "", watch_cve: true };

function ServerModal({ projectId, server, onClose }: { projectId: number; server?: Server; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState(server ? { ...emptyServer, ...server } : emptyServer);
  const set = (k: keyof typeof emptyServer, v: string) => setF((x) => ({ ...x, [k]: v }));
  const save = useMutation({
    mutationFn: () => (server ? api(`/servers/${server.id}`, "PUT", f) : api(`/projects/${projectId}/servers`, "POST", f)),
    onSuccess: () => { qc.invalidateQueries(); onClose(); },
  });
  const input = (k: keyof typeof emptyServer, label: string, ph = "", hint?: string) => (
    <Field label={label} hint={hint}><input value={f[k]} placeholder={ph} onChange={(e) => set(k, e.target.value)} /></Field>
  );
  return (
    <Modal title={server ? "Modifier le serveur" : "Ajouter un serveur"} onClose={onClose} wide>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="grid gap-4 sm:grid-cols-2">
        {input("label", "Nom", "Serveur web principal")}
        {input("provider", "Hébergeur", "OVH, Hetzner, AWS…")}
        {input("hostname", "Nom d'hôte", "srv1.deva2.fr")}
        {input("ip", "Adresse IP", "51.xx.xx.xx")}
        {input("os", "Système", "Ubuntu 24.04")}
        {input("location", "Localisation", "Gravelines (FR)")}
        <div className="sm:col-span-2">{input("specs", "Ressources", "2 vCPU / 4 Go RAM / 80 Go SSD")}</div>
        <div className="sm:col-span-2">
          <Field label="Comment y accéder" hint=" Ne jamais écrire de mot de passe ici : indiquez seulement le principe (ex : SSH par clé, utilisateur deploy).">
            <textarea rows={2} value={f.access_info} onChange={(e) => set("access_info", e.target.value)} />
          </Field>
        </div>
        <div className="sm:col-span-2"><Field label="Notes"><textarea rows={2} value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field></div>
        <div className="sm:col-span-2"><ErrorMsg error={save.error} /></div>
        <div className="flex flex-wrap justify-end gap-2 sm:col-span-2">
          <Button type="button" variant="ghost" onClick={onClose}>Annuler</Button>
          <Button type="submit" busy={save.isPending}>Enregistrer</Button>
        </div>
      </form>
    </Modal>
  );
}

function TechModal({ projectId, tech, onClose }: { projectId: number; tech?: Tech; onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState(tech ? { name: tech.name, version: tech.version, category: tech.category, watch_cve: tech.watch_cve } : emptyTech);
  const save = useMutation({
    mutationFn: () => (tech ? api(`/technologies/${tech.id}`, "PUT", f) : api(`/projects/${projectId}/technologies`, "POST", f)),
    onSuccess: () => { qc.invalidateQueries(); onClose(); },
  });
  return (
    <Modal title={tech ? "Modifier la technologie" : "Ajouter une technologie"} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <Field label="Nom *" hint="Ex : nginx, wordpress, php, postgresql, node, laravel"><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Version" hint="Plus c'est précis (ex : 1.24.0), plus la veille de failles est fiable"><input value={f.version} onChange={(e) => setF({ ...f, version: e.target.value })} /></Field>
        <Field label="Catégorie"><input value={f.category} placeholder="Serveur web, base de données…" onChange={(e) => setF({ ...f, category: e.target.value })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.watch_cve} onChange={(e) => setF({ ...f, watch_cve: e.target.checked })} /> Surveiller les failles de sécurité (CVE)</label>
        <ErrorMsg error={save.error} />
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Annuler</Button>
          <Button type="submit" busy={save.isPending}>Enregistrer</Button>
        </div>
      </form>
    </Modal>
  );
}

function Sparkline({ checks }: { checks: Check[] }) {
  if (checks.length < 2) return <Empty>Pas encore assez de mesures.</Empty>;
  const vals = checks.map((c) => c.latency_ms ?? 0);
  const max = Math.max(...vals, 1);
  const pts = checks.map((c, i) => `${(i / (checks.length - 1)) * 100},${36 - ((c.latency_ms ?? 0) / max) * 32}`).join(" ");
  return (
    <div>
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-24 w-full">
        <polyline points={pts} fill="none" stroke="#1f5f4f" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-1 flex h-2 gap-px">
        {checks.slice(-60).map((c, i) => <span key={i} title={`${fmtDateTime(c.ts)} – ${c.ok ? "OK" : c.error}`} className={`flex-1 rounded-sm ${c.ok ? "bg-emerald-400" : "bg-red-500"}`} />)}
      </div>
      <p className="mt-2 text-xs text-slate-400">Temps de réponse (max {max} ms) · barre verte/rouge = disponibilité</p>
    </div>
  );
}

export default function ProjectDetail() {
  const { id } = useParams();
  const pid = Number(id);
  const nav = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [server, setServer] = useState<Server | "new" | null>(null);
  const [tech, setTech] = useState<Tech | "new" | null>(null);

  const project = useQuery({ queryKey: ["project", pid], queryFn: () => api<Project>(`/projects/${pid}`) });
  const checks = useQuery({ queryKey: ["checks", pid], queryFn: () => api<Check[]>(`/projects/${pid}/checks?limit=200`) });
  const vulns = useQuery({ queryKey: ["vulns", pid], queryFn: () => api<Vuln[]>(`/security/vulnerabilities?project_id=${pid}`) });

  const refresh = () => qc.invalidateQueries();
  const checkNow = useMutation({ mutationFn: () => api(`/projects/${pid}/check`, "POST"), onSuccess: refresh });
  const scan = useMutation({ mutationFn: () => api(`/security/scan?project_id=${pid}`, "POST"), onSuccess: refresh });
  const del = useMutation({ mutationFn: () => api(`/projects/${pid}`, "DELETE"), onSuccess: () => { refresh(); nav("/projets"); } });
  const delServer = useMutation({ mutationFn: (sid: number) => api(`/servers/${sid}`, "DELETE"), onSuccess: refresh });
  const delTech = useMutation({ mutationFn: (tid: number) => api(`/technologies/${tid}`, "DELETE"), onSuccess: refresh });
  const dismiss = useMutation({ mutationFn: (vid: number) => api(`/security/vulnerabilities/${vid}/dismiss`, "POST"), onSuccess: refresh });

  const p = project.data;
  if (!p) return project.error ? <ErrorMsg error={project.error} /> : <Loading />;
  const sslDays = p.ssl_expires_at ? Math.floor((new Date(p.ssl_expires_at).getTime() - Date.now()) / 86_400_000) : null;

  return (
    <>
      <Link to="/projets" className="text-sm text-slate-500 hover:text-brand-600">← Tous les projets</Link>
      <PageHeader title={p.name} subtitle={p.description || undefined}
        action={<div className="flex flex-wrap gap-2">
          <Button variant="soft" busy={checkNow.isPending} onClick={() => checkNow.mutate()}>Vérifier maintenant</Button>
          <Button variant="ghost" onClick={() => setEditing(true)}>Modifier</Button>
          <Button variant="danger" onClick={() => confirm(`Supprimer « ${p.name} » et tout son historique ?`) && del.mutate()}>Supprimer</Button>
        </div>} />
      <ErrorMsg error={checkNow.error} />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Card><p className="text-xs text-slate-400">Statut</p><div className="mt-1"><StatusDot status={p.status} /></div></Card>
        <Card><p className="text-xs text-slate-400">Site</p><a href={p.url} target="_blank" rel="noreferrer noopener" className="mt-1 block truncate text-sm font-medium text-brand-600">{p.url}</a></Card>
        <Card><p className="text-xs text-slate-400">Certificat SSL</p><p className="mt-1 text-sm font-medium">{sslDays == null ? "—" : sslDays < 0 ? "Expiré" : `${sslDays} jours (${fmtDate(p.ssl_expires_at)})`}</p></Card>
        <Card><p className="text-xs text-slate-400">Dernier contrôle</p><p className="mt-1 text-sm font-medium">{fmtDateTime(p.last_checked_at)}{p.last_latency_ms != null && ` · ${p.last_latency_ms} ms`}</p></Card>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Disponibilité"><Sparkline checks={checks.data ?? []} /></Card>
        <Card title="Monitoring">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">Outils</dt><dd>{p.monitoring_tools || "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Fréquence</dt><dd>{p.monitoring_enabled ? `toutes les ${p.check_interval_min} min` : "désactivé"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Dépôt</dt><dd>{p.repo_url ? <a className="text-brand-600" href={p.repo_url} target="_blank" rel="noreferrer noopener">ouvrir</a> : "—"}</dd></div>
          </dl>
          {p.missing_headers.length > 0 && (
            <div className="mt-4 rounded bg-amber-50 p-3 text-sm text-amber-800">
              <p className="font-medium">En-têtes de sécurité manquants</p>
              <p className="mt-1">{p.missing_headers.join(", ")}</p>
            </div>
          )}
        </Card>
        <Card title="Serveurs" className="lg:col-span-2" action={<Button variant="soft" onClick={() => setServer("new")}>+ Serveur</Button>}>
          {p.servers.length === 0 ? <Empty>Aucun serveur renseigné. Ajoutez l'hébergeur, l'IP, le système…</Empty> : (
            <div className="grid gap-4 md:grid-cols-2">
              {p.servers.map((s) => (
                <div key={s.id} className="rounded border border-slate-200 p-4 text-sm">
                  <div className="flex justify-between"><p className="font-semibold">{s.label || s.hostname || "Serveur"}</p>
                    <span className="space-x-3 text-xs"><button className="text-brand-600" onClick={() => setServer(s)}>Modifier</button><button className="text-red-600" onClick={() => confirm("Supprimer ce serveur ?") && delServer.mutate(s.id)}>Supprimer</button></span></div>
                  <dl className="mt-2 grid grid-cols-[100px_1fr] gap-y-1 text-slate-600">
                    {([["Hébergeur", s.provider], ["Hôte", s.hostname], ["IP", s.ip], ["Système", s.os], ["Lieu", s.location], ["Ressources", s.specs], ["Accès", s.access_info], ["Notes", s.notes]] as const).filter(([, v]) => v).map(([k, v]) => (
                      <Fragment key={k}><dt className="text-slate-400">{k}</dt><dd className="whitespace-pre-line break-words">{v}</dd></Fragment>
                    ))}
                  </dl>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title="Technologies" className="lg:col-span-2" action={<div className="flex flex-wrap gap-2">
          <Button variant="ghost" busy={scan.isPending} onClick={() => scan.mutate()}>Chercher des failles</Button>
          <Button variant="soft" onClick={() => setTech("new")}>+ Technologie</Button></div>}>
          <ErrorMsg error={scan.error} />
          {p.technologies.length === 0 ? <Empty>Listez ici vos technos (nginx, PHP, WordPress…) : le Hub surveillera les failles de sécurité qui les concernent.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {p.technologies.map((t) => (
                <li key={t.id} className="flex items-center justify-between py-2.5 text-sm">
                  <span><b>{t.name}</b> {t.version} {t.category && <span className="text-slate-400">· {t.category}</span>}</span>
                  <span className="flex items-center gap-3">
                    {t.watch_cve ? <Badge tone="green">Surveillée</Badge> : <Badge>Non surveillée</Badge>}
                    <button className="text-xs text-brand-600" onClick={() => setTech(t)}>Modifier</button>
                    <button className="text-xs text-red-600" onClick={() => confirm("Supprimer ?") && delTech.mutate(t.id)}>Supprimer</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Failles de sécurité détectées" className="lg:col-span-2">
          {!vulns.data?.length ? <Empty>Aucune faille connue détectée </Empty> : (
            <ul className="divide-y divide-slate-100">
              {vulns.data.map((v) => (
                <li key={v.id} className="py-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2">
                      <a className="font-semibold text-brand-600" target="_blank" rel="noreferrer noopener" href={`https://nvd.nist.gov/vuln/detail/${v.cve_id}`}>{v.cve_id}</a>
                      <Badge tone={(v.cvss ?? 0) >= 9 ? "red" : (v.cvss ?? 0) >= 7 ? "amber" : "slate"}>CVSS {v.cvss ?? "?"}</Badge>
                      {v.exploited && <Badge tone="red">Exploitée activement</Badge>}
                      <span className="text-slate-400">{v.tech_name} {v.tech_version}</span>
                    </span>
                    <button className="text-xs text-slate-500 hover:text-slate-800" onClick={() => dismiss.mutate(v.id)}>Ignorer (non concerné)</button>
                  </div>
                  <p className="mt-1 line-clamp-2 text-slate-500">{v.summary}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {editing && <ProjectFormModal id={p.id} initial={{ name: p.name, url: p.url, description: p.description, environment: p.environment, repo_url: p.repo_url, monitoring_tools: p.monitoring_tools, notes: p.notes, monitoring_enabled: p.monitoring_enabled, public_status: p.public_status, check_interval_min: p.check_interval_min, expected_status: p.expected_status }} onClose={() => setEditing(false)} />}
      {server && <ServerModal projectId={p.id} server={server === "new" ? undefined : server} onClose={() => setServer(null)} />}
      {tech && <TechModal projectId={p.id} tech={tech === "new" ? undefined : tech} onClose={() => setTech(null)} />}
    </>
  );
}
