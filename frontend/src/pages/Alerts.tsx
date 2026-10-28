import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Channel, User, Vuln, api } from "../api";
import { Badge, Button, Card, Empty, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDateTime } from "../ui";

const SEV = { critical: ["red", "Critique"], warning: ["amber", "Attention"], info: ["blue", "Info"] } as const;
const KIND: Record<string, string> = { down: "Site down", recovered: "Rétabli", ssl: "Certificat SSL", attack: "Attaque / anomalie", vuln: "Faille de sécurité", tax: "Échéance", invoice: "Facture", renewal: "Renouvellement", digest: "Résumé du jour" };

const CHANNEL_TYPES: Record<string, { label: string; fields: { key: string; label: string; placeholder?: string; secret?: boolean }[]; help: string }> = {
  email: { label: "E-mail", help: "Nécessite la configuration SMTP (Paramètres > Intégrations).", fields: [{ key: "to", label: "Adresse(s) destinataire(s)", placeholder: "alertes@deva2.fr" }] },
  slack: { label: "Slack", help: "Slack > Apps > Incoming Webhooks > Ajouter à un canal, puis copiez l'URL.", fields: [{ key: "webhook_url", label: "URL du webhook Slack", secret: true }] },
  discord: { label: "Discord", help: "Paramètres du salon > Intégrations > Webhooks > Nouveau webhook > Copier l'URL.", fields: [{ key: "webhook_url", label: "URL du webhook Discord", secret: true }] },
  telegram: { label: "Telegram", help: "Créez un bot avec @BotFather (jeton), puis récupérez votre chat_id via @userinfobot.", fields: [{ key: "bot_token", label: "Jeton du bot", secret: true }, { key: "chat_id", label: "Chat ID" }] },
  webhook: { label: "Webhook générique", help: "Le Hub enverra un POST JSON {title, message, severity} à cette URL.", fields: [{ key: "url", label: "URL", secret: true }] },
};

function ChannelModal({ channel, onClose }: { channel?: Channel; onClose: () => void }) {
  const qc = useQueryClient();
  const [type, setType] = useState(channel?.type ?? "slack");
  const [name, setName] = useState(channel?.name ?? "");
  const [sev, setSev] = useState(channel?.min_severity ?? "warning");
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  const [config, setConfig] = useState<Record<string, string>>({});
  const t = CHANNEL_TYPES[type];
  const save = useMutation({
    mutationFn: () => {
      const body = { name, type, min_severity: sev, enabled, config };
      return channel ? api(`/channels/${channel.id}`, "PUT", body) : api("/channels", "POST", body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["channels"] }); onClose(); },
  });
  return (
    <Modal title={channel ? "Modifier le canal" : "Nouveau canal de notification"} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <Field label="Nom"><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Slack #alertes" /></Field>
        <Field label="Type">
          <select value={type} disabled={!!channel} onChange={(e) => { setType(e.target.value); setConfig({}); }}>
            {Object.entries(CHANNEL_TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </Field>
        <p className="rounded bg-slate-50 p-3 text-xs text-slate-500">{t.help}</p>
        {t.fields.map((f) => (
          <Field key={f.key} label={f.label} hint={channel?.config_keys.includes(f.key) ? "Déjà enregistré – laissez vide pour le conserver" : undefined}>
            <input type={f.secret ? "password" : "text"} autoComplete="off" placeholder={f.placeholder} required={!channel} value={config[f.key] ?? ""} onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })} />
          </Field>
        ))}
        <Field label="Envoyer à partir de la gravité">
          <select value={sev} onChange={(e) => setSev(e.target.value)}>
            <option value="info">Tout (info, attention, critique)</option><option value="warning">Attention et critique</option><option value="critical">Critique uniquement</option>
          </select>
        </Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Canal actif</label>
        <ErrorMsg error={save.error} />
        <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="submit" busy={save.isPending}>Enregistrer</Button></div>
      </form>
    </Modal>
  );
}

function Channels() {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Channel | "new" | null>(null);
  const [msg, setMsg] = useState<string>("");
  const { data } = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/channels") });
  const del = useMutation({ mutationFn: (id: number) => api(`/channels/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }) });
  const test = useMutation({
    mutationFn: (id: number) => api(`/channels/${id}/test`, "POST"),
    onSuccess: () => setMsg(" Message de test envoyé"),
    onError: (e) => setMsg(` ${e instanceof Error ? e.message : e}`),
  });
  return (
    <Card title="Où recevoir les alertes ?" action={<Button variant="soft" onClick={() => setEdit("new")}>+ Canal</Button>}>
      {msg && <p className="mb-3 text-sm">{msg}</p>}
      {!data?.length ? <Empty>Aucun canal : les alertes restent visibles ici mais ne sont envoyées nulle part. Ajoutez un e-mail, Slack, Discord ou Telegram.</Empty> : (
        <ul className="divide-y divide-slate-100">
          {data.map((c) => (
            <li key={c.id} className="flex items-center justify-between py-3 text-sm">
              <span><b>{c.name}</b> <Badge>{CHANNEL_TYPES[c.type]?.label}</Badge> {!c.enabled && <Badge tone="amber">Désactivé</Badge>}</span>
              <span className="flex gap-3 text-xs">
                <button className="text-brand-600" onClick={() => { setMsg(""); test.mutate(c.id); }}>Envoyer un test</button>
                <button className="text-brand-600" onClick={() => setEdit(c)}>Modifier</button>
                <button className="text-red-600" onClick={() => confirm("Supprimer ce canal ?") && del.mutate(c.id)}>Supprimer</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {edit && <ChannelModal channel={edit === "new" ? undefined : edit} onClose={() => setEdit(null)} />}
    </Card>
  );
}

export default function Alerts({ user }: { user: User }) {
  const qc = useQueryClient();
  const [onlyOpen, setOnlyOpen] = useState(true);
  const alerts = useQuery({ queryKey: ["alerts", onlyOpen], queryFn: () => api<Alert[]>(`/alerts?only_open=${onlyOpen}`), refetchInterval: 30_000 });
  const vulns = useQuery({ queryKey: ["vulns"], queryFn: () => api<Vuln[]>("/security/vulnerabilities") });
  const inval = () => qc.invalidateQueries();
  const ack = useMutation({ mutationFn: (id: number) => api(`/alerts/${id}/ack`, "POST"), onSuccess: inval });
  const ackAll = useMutation({ mutationFn: () => api("/alerts/ack-all", "POST"), onSuccess: inval });
  const scan = useMutation({ mutationFn: () => api("/security/scan", "POST"), onSuccess: inval });
  const dismiss = useMutation({ mutationFn: (id: number) => api(`/security/vulnerabilities/${id}/dismiss`, "POST"), onSuccess: inval });

  return (
    <>
      <PageHeader title="Alertes & sécurité" subtitle="Sites en panne, attaques, certificats, failles critiques et échéances." />
      <div className="space-y-6">
        <Card title="Alertes" action={<div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-500"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> Seulement les non traitées</label>
          <Button variant="ghost" onClick={() => ackAll.mutate()}>Tout marquer comme lu</Button></div>}>
          {alerts.isLoading ? <Loading /> : !alerts.data?.length ? <Empty>Aucune alerte </Empty> : (
            <ul className="divide-y divide-slate-100">
              {alerts.data.map((a) => (
                <li key={a.id} className={`py-3 ${a.acknowledged ? "opacity-50" : ""}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
                        <Badge tone={SEV[a.severity][0]}>{SEV[a.severity][1]}</Badge> {a.title}
                      </p>
                      <p className="mt-1 whitespace-pre-line text-sm text-slate-500">{a.message}</p>
                      <p className="mt-1 text-xs text-slate-400">{KIND[a.kind] ?? a.kind} · {fmtDateTime(a.created_at)}{a.delivery && ` · Envoi : ${a.delivery.replace(/\n/g, ", ")}`}</p>
                    </div>
                    {!a.acknowledged && <Button variant="ghost" onClick={() => ack.mutate(a.id)}>Traité</Button>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Veille des failles de sécurité (CVE)" action={<Button variant="soft" busy={scan.isPending} onClick={() => scan.mutate()}>Lancer une recherche</Button>}>
          <p className="mb-3 text-xs text-slate-400">Le Hub compare les technologies déclarées dans chaque projet avec la base NVD et le catalogue CISA des failles exploitées. La recherche étant par mot-clé, vérifiez que votre version est bien concernée.</p>
          <ErrorMsg error={scan.error} />
          {!vulns.data?.length ? <Empty>Aucune faille détectée. Pensez à renseigner les technologies de vos projets.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {vulns.data.map((v) => (
                <li key={v.id} className="py-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex flex-wrap items-center gap-2">
                      <a className="font-semibold text-brand-600" target="_blank" rel="noreferrer noopener" href={`https://nvd.nist.gov/vuln/detail/${v.cve_id}`}>{v.cve_id}</a>
                      <Badge tone={(v.cvss ?? 0) >= 9 ? "red" : (v.cvss ?? 0) >= 7 ? "amber" : "slate"}>CVSS {v.cvss ?? "?"}</Badge>
                      {v.exploited && <Badge tone="red">Exploitée activement</Badge>}
                      <span className="text-slate-500">{v.project_name} · {v.tech_name} {v.tech_version}</span>
                    </span>
                    <button className="text-xs text-slate-500 hover:text-slate-800" onClick={() => dismiss.mutate(v.id)}>Ignorer</button>
                  </div>
                  <p className="mt-1 line-clamp-2 text-slate-500">{v.summary}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {user.role === "admin" && <Channels />}
      </div>
    </>
  );
}
