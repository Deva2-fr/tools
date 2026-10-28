import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DirectoryUser, Field as IField, Signers, User, api } from "../api";
import { Badge, Button, Card, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDateTime } from "../ui";
import { CompanyLookup, Hit } from "./crm/CompanyLookup";

const GROUPS: Record<string, { title: string; test?: string; intro: string }> = {
  company: { title: "Ma société (devis & factures)", intro: "Tapez le nom de la société (ou son SIREN) et choisissez-la : raison sociale, forme juridique, SIRET, TVA et adresse se remplissent seuls. Ces informations apparaissent sur les devis, factures et notes de frais. Guide : section 8." },
  google: { title: "Google Drive (notes de frais)", test: "google", intro: "Chaque note de frais enregistrée est déposée en PDF dans Deva2 › Administration › Comptabilité › Note de frais. Guide : section 4." },
  email: { title: "E-mail d'envoi des alertes (SMTP)", test: "smtp", intro: "Pour recevoir les alertes par e-mail. Guide : section 5." },
  ai: { title: "Assistant IA (devis)", test: "ai", intro: "Clé API Anthropic (Claude) : permet d'améliorer les devis avec l'IA (bouton « Améliorer avec l'IA » dans un devis). Guide : section 8." },
  qonto: { title: "Banque Qonto (trésorerie)", test: "qonto", intro: "Synchronise automatiquement (toutes les heures) vos comptes, transactions, devis et factures Qonto. Lecture seule. Guide : section 12." },
  outlook: { title: "Microsoft 365 (optionnel)", test: "outlook", intro: "Uniquement pour une boîte hébergée chez Microsoft 365 (qui n'accepte pas l'IMAP) : elle apparaît alors comme un bouton de plus dans Mails. Guide : section 3, annexe." },
  security: { title: "Veille de sécurité", test: "nvd", intro: "Optionnel, mais une clé NVD gratuite rend la veille plus rapide. Guide : section 6." },
};

function IntegrationField({ f }: { f: IField }) {
  const qc = useQueryClient();
  const [v, setV] = useState(f.value);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: () => api(`/integrations/${f.key}`, "PUT", { value: v }),
    onSuccess: () => { setSaved(true); if (f.secret) setV(""); qc.invalidateQueries({ queryKey: ["integrations"] }); setTimeout(() => setSaved(false), 2000); },
  });
  const common = {
    value: v, autoComplete: "off", onChange: (e: React.ChangeEvent<HTMLInputElement & HTMLTextAreaElement>) => setV(e.target.value),
    placeholder: f.secret && f.is_set ? "•••••••• (enregistré – tapez pour remplacer)" : "",
  };
  return (
    <Field label={f.label} hint={f.help}>
      <div className="flex gap-2">
        {f.multiline ? <textarea rows={3} {...common} className="font-mono text-xs" /> : <input type={f.secret ? "password" : "text"} {...common} />}
        <Button variant="ghost" type="button" busy={save.isPending} disabled={f.secret && !v && !f.is_set} onClick={() => save.mutate()}>{saved ? "✓" : f.secret && !v && f.is_set ? "Effacer" : "OK"}</Button>
      </div>
    </Field>
  );
}

interface Box { id: number; name: string; host: string; port: number; username: string; has_password: boolean; sent_folder: string; webmail_url: string; position: number; active: boolean; last_synced_at: string | null; last_error: string }
const blankBox = { name: "", host: "", port: 993, username: "", password: "", sent_folder: "", webmail_url: "", position: 0, active: true };

/** Boîtes mail lues en IMAP : une par adresse (contact@, compta@, boîtes personnelles…). */
function Mailboxes() {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<(typeof blankBox & { id?: number; has_password?: boolean }) | null>(null);
  const [result, setResult] = useState<Record<number, string>>({});
  const boxes = useQuery({ queryKey: ["mailboxes"], queryFn: () => api<Box[]>("/mail/mailboxes") });
  const inval = () => { qc.invalidateQueries({ queryKey: ["mailboxes"] }); qc.invalidateQueries({ queryKey: ["mail-status"] }); };
  const save = useMutation({
    mutationFn: () => { const { id, has_password: _h, ...body } = edit!; return id ? api(`/mail/mailboxes/${id}`, "PUT", body) : api("/mail/mailboxes", "POST", body); },
    onSuccess: () => { inval(); setEdit(null); },
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/mail/mailboxes/${id}`, "DELETE"), onSuccess: inval });
  const test = useMutation({
    mutationFn: (id: number) => api<{ message: string }>(`/mail/mailboxes/${id}/test`, "POST"),
    onSuccess: (r, id) => setResult((x) => ({ ...x, [id]: r.message })),
    onError: (e, id) => setResult((x) => ({ ...x, [id]: `Échec : ${e instanceof Error ? e.message : e}` })),
  });
  const set = (k: keyof typeof blankBox, v: string | number | boolean) => setEdit((x) => x && { ...x, [k]: v });
  return (
    <Card title="Boîtes mail (IMAP)" action={<Button variant="soft" onClick={() => setEdit({ ...blankBox, position: boxes.data?.length ?? 0 })}>+ Boîte mail</Button>}>
      <p className="mb-4 text-xs text-slate-400">Une ligne par adresse à suivre (contact@, compta@, boîtes personnelles…) : chacune a son bouton dans la page Mails. Mêmes réglages que dans Outlook (Fichier → Paramètres du compte). Lecture seule : le Hub ne marque rien comme lu et ne supprime rien. Guide : section 3.</p>
      {!boxes.data?.length ? <p className="text-sm text-slate-500">Aucune boîte pour l'instant.</p> : (
        <ul className="divide-y divide-slate-100">
          {boxes.data.map((b) => (
            <li key={b.id} className="py-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span><b>{b.name}</b> <span className="text-slate-500">{b.username}</span> <span className="text-xs text-slate-400">· {b.host}:{b.port}</span>{!b.active && <> <Badge>désactivée</Badge></>}</span>
                <span className="flex items-center gap-3 text-xs">
                  <Button variant="soft" busy={test.isPending && test.variables === b.id} onClick={() => test.mutate(b.id)}>Tester la connexion</Button>
                  <button className="text-brand-600" onClick={() => setEdit({ ...b, password: "" })}>Modifier</button>
                  <button className="text-red-600" onClick={() => confirm(`Retirer la boîte « ${b.name} » du Hub ? (Rien n'est supprimé sur le serveur mail.)`) && del.mutate(b.id)}>Supprimer</button>
                </span>
              </div>
              {result[b.id] ? <p className="mt-1 text-xs">{result[b.id]}</p>
                : b.last_error ? <p className="mt-1 text-xs text-red-700">Dernière synchronisation en échec : {b.last_error}</p>
                : b.last_synced_at && <p className="mt-1 text-xs text-slate-400">Synchronisée le {fmtDateTime(b.last_synced_at)}</p>}
            </li>
          ))}
        </ul>
      )}
      <ErrorMsg error={del.error} />
      {edit && (
        <Modal title={edit.id ? `Modifier « ${edit.name} »` : "Nouvelle boîte mail"} onClose={() => setEdit(null)}>
          <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <Field label="Nom du bouton *" hint="Ex : Contact, Compta, Hugo"><input required maxLength={80} value={edit.name} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Identifiant *" hint="En général l'adresse e-mail complète"><input required autoComplete="off" value={edit.username} onChange={(e) => set("username", e.target.value)} /></Field>
            <Field label="Serveur IMAP *" hint="Ex : ssl0.ovh.net, imap.ionos.fr"><input required value={edit.host} onChange={(e) => set("host", e.target.value)} /></Field>
            <Field label="Port" hint="993 (SSL) ou 143 (STARTTLS)"><input type="number" min={1} max={65535} value={edit.port} onChange={(e) => set("port", Number(e.target.value))} /></Field>
            <div className="sm:col-span-2"><Field label={edit.id ? "Mot de passe" : "Mot de passe *"} hint={edit.has_password ? "Enregistré (chiffré). Laissez vide pour le conserver." : "Celui de la boîte mail, stocké chiffré"}><input type="password" autoComplete="new-password" required={!edit.id} value={edit.password} onChange={(e) => set("password", e.target.value)} placeholder={edit.has_password ? "••••••••" : ""} /></Field></div>
            <Field label="Dossier des envoyés" hint="Laissez vide : détecté automatiquement"><input value={edit.sent_folder} onChange={(e) => set("sent_folder", e.target.value)} /></Field>
            <Field label="Adresse du webmail" hint="Facultatif, pour le bouton « Ouvrir le webmail »"><input type="url" value={edit.webmail_url} onChange={(e) => set("webmail_url", e.target.value)} placeholder="https://" /></Field>
            <Field label="Ordre d'affichage"><input type="number" value={edit.position} onChange={(e) => set("position", Number(e.target.value))} /></Field>
            <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" className="!w-auto" checked={edit.active} onChange={(e) => set("active", e.target.checked)} /> Active (relue toutes les 5 minutes)</label>
            <div className="sm:col-span-2"><ErrorMsg error={save.error} /></div>
            <div className="flex flex-wrap justify-end gap-2 sm:col-span-2"><Button type="button" variant="ghost" onClick={() => setEdit(null)}>Annuler</Button><Button type="submit" busy={save.isPending}>Enregistrer</Button></div>
          </form>
        </Modal>
      )}
    </Card>
  );
}

/** Président et associé : leurs signatures sont demandées sur chaque note de frais. */
function ExpenseSigners() {
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ["directory"], queryFn: () => api<DirectoryUser[]>("/users/directory") });
  const current = useQuery({ queryKey: ["expense-signers"], queryFn: () => api<Signers>("/expenses/signers") });
  const [f, setF] = useState<{ president: number | null; partner: number | null } | null>(null);
  useEffect(() => { if (current.data && !f) setF({ president: current.data.president?.id ?? null, partner: current.data.partner?.id ?? null }); }, [current.data, f]);
  const save = useMutation({ mutationFn: () => api("/expenses/signers", "PUT", f), onSuccess: () => qc.invalidateQueries({ queryKey: ["expense-signers"] }) });
  if (!f) return null;
  return (
    <Card title="Signataires des notes de frais" action={<Button variant="soft" busy={save.isPending} onClick={() => save.mutate()}>Enregistrer</Button>}>
      <p className="mb-4 text-xs text-slate-400">Chaque note de frais porte trois signatures : le demandeur, le président et l'associé. Le président et l'associé voient toutes les notes et y apposent leur propre signature.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {(["president", "partner"] as const).map((k) => (
          <Field key={k} label={k === "president" ? "Président" : "Associé"}>
            <select value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— Non désigné —</option>
              {(people.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}{p.name !== p.email ? ` (${p.email})` : ""}</option>)}
            </select>
          </Field>
        ))}
      </div>
      {save.isSuccess && <p className="mt-3 text-sm text-emerald-700">Enregistré.</p>}
      <ErrorMsg error={save.error} />
    </Card>
  );
}

/** « Ma société » : recherche dans l'annuaire des entreprises, puis enregistrement des champs trouvés. */
function CompanyAutofill({ onDone }: { onDone: () => void }) {
  const [msg, setMsg] = useState("");
  const fill = useMutation({
    mutationFn: async ({ v, hit }: { v: Record<string, unknown>; hit?: Hit }) => {
      const str = (k: string) => String(v[k] ?? "").trim();
      const values: Record<string, string> = {
        company_name: str("name"),
        company_siret: str("siret"),
        company_vat: str("vat_number"),
        company_address: [str("address"), `${str("postal_code")} ${str("city")}`.trim()].filter(Boolean).join("\n"),
        company_legal_form: hit?.legal_form ?? "",
      };
      for (const [k, val] of Object.entries(values)) if (val) await api(`/integrations/${k}`, "PUT", { value: val });
      return values.company_name;
    },
    onSuccess: (name) => { setMsg(`Informations de « ${name} » enregistrées : complétez le capital, l'e-mail, le téléphone et l'IBAN.`); onDone(); },
  });
  return (
    <div className="mb-4">
      <CompanyLookup syncName={false} autoFocus={false} onPick={(v, hit) => hit && fill.mutate({ v, hit })} />
      {msg && <p className="mt-2 text-sm text-emerald-700">{msg}</p>}
      <ErrorMsg error={fill.error} />
    </div>
  );
}

/** Connexion OAuth à Qonto : nécessaire pour les devis (import et envoi depuis le Hub). */
function QontoOAuth() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["billing-qonto"], queryFn: () => api<{ oauth_configured: boolean; oauth_connected: boolean; redirect_uri: string }>("/billing/qonto") });
  const connect = useMutation({ mutationFn: () => api<{ url: string }>("/billing/qonto/connect"), onSuccess: (r) => { window.location.href = r.url; } });
  const disconnect = useMutation({ mutationFn: () => api("/billing/qonto/disconnect", "POST"), onSuccess: () => qc.invalidateQueries({ queryKey: ["billing-qonto"] }) });
  const params = new URLSearchParams(window.location.search);
  const s = st.data;
  if (!s) return null;
  return (
    <div className="mb-4 rounded border border-slate-200 bg-slate-50 p-3 text-sm">
      <p className="font-medium text-slate-800">Connexion Qonto pour les devis {s.oauth_connected ? <Badge tone="green">connecté</Badge> : <Badge tone="amber">non connecté</Badge>}</p>
      <p className="mt-1 text-xs text-slate-500">La clé API suffit pour les comptes, transactions et factures. Les <b>devis</b> (import et envoi depuis le Hub) demandent une connexion OAuth : créez une application sur le portail développeur Qonto avec l'adresse de redirection <code className="rounded bg-white px-1">{s.redirect_uri}</code>, renseignez son ID et son secret ci-dessous, puis connectez-vous.</p>
      {params.get("qonto") === "connected" && <p className="mt-2 text-xs text-emerald-700">Qonto est connecté.</p>}
      {params.get("qonto_error") && <p className="mt-2 text-xs text-red-700">Connexion refusée : {params.get("qonto_error")}</p>}
      <div className="mt-2 flex gap-2">
        {s.oauth_connected
          ? <Button variant="ghost" onClick={() => confirm("Déconnecter Qonto pour les devis ?") && disconnect.mutate()}>Déconnecter</Button>
          : <Button variant="soft" disabled={!s.oauth_configured} busy={connect.isPending} onClick={() => connect.mutate()}>Se connecter avec Qonto</Button>}
      </div>
      <ErrorMsg error={connect.error} />
    </div>
  );
}

function Integrations() {
  const qc = useQueryClient();
  const [result, setResult] = useState<Record<string, string>>({});
  const [version, setVersion] = useState(0); // remonte les champs après un remplissage automatique
  const { data } = useQuery({ queryKey: ["integrations"], queryFn: () => api<IField[]>("/integrations") });
  const test = useMutation({
    mutationFn: (s: string) => api<{ message: string }>(`/integrations/test/${s}`, "POST"),
    onSuccess: (r, s) => setResult((x) => ({ ...x, [s]: ` ${r.message}` })),
    onError: (e, s) => setResult((x) => ({ ...x, [s]: ` ${e instanceof Error ? e.message : e}` })),
  });
  if (!data) return <Loading />;
  return (
    <div className="space-y-6">
      <Mailboxes />
      <ExpenseSigners />
      {Object.entries(GROUPS).map(([g, meta]) => (
        <Card key={g} title={meta.title} action={meta.test && <Button variant="soft" busy={test.isPending && test.variables === meta.test} onClick={() => test.mutate(meta.test!)}>Tester la connexion</Button>}>
          <p className="mb-4 text-xs text-slate-400">{meta.intro}</p>
          {meta.test && result[meta.test] && <p className="mb-4 text-sm">{result[meta.test]}</p>}
          {g === "qonto" && <QontoOAuth />}
          {g === "company" && <CompanyAutofill onDone={() => qc.invalidateQueries({ queryKey: ["integrations"] }).then(() => setVersion((v) => v + 1))} />}
          <div className="grid gap-4 sm:grid-cols-2">
            {data.filter((f) => f.group === g).map((f) => <div key={`${f.key}-${version}`} className={f.multiline ? "sm:col-span-2" : ""}><IntegrationField f={f} /></div>)}
          </div>
        </Card>
      ))}
    </div>
  );
}

function Security({ user }: { user: User }) {
  const qc = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [pwMsg, setPwMsg] = useState("");
  const start = useMutation({ mutationFn: () => api<{ secret: string; otpauth_uri: string }>("/auth/totp/setup", "POST"), onSuccess: setSetup });
  const enable = useMutation({ mutationFn: () => api("/auth/totp/enable", "POST", { code }), onSuccess: () => { setSetup(null); setCode(""); qc.invalidateQueries({ queryKey: ["me"] }); } });
  const disable = useMutation({ mutationFn: () => api("/auth/totp/disable", "POST", { code }), onSuccess: () => { setCode(""); qc.invalidateQueries({ queryKey: ["me"] }); } });
  const change = useMutation({ mutationFn: () => api("/auth/password", "POST", pw), onSuccess: () => { setPwMsg(" Mot de passe modifié"); setPw({ current_password: "", new_password: "" }); }, onError: () => setPwMsg("") });
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Double authentification (2FA)" action={user.totp_enabled ? <Badge tone="green">Activée</Badge> : <Badge tone="amber">Non activée</Badge>}>
        {user.totp_enabled ? (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Pour la désactiver, saisissez un code de votre application.</p>
            <input inputMode="numeric" maxLength={6} placeholder="000000" value={code} onChange={(e) => setCode(e.target.value)} />
            <ErrorMsg error={disable.error} />
            <Button variant="danger" onClick={() => disable.mutate()}>Désactiver la 2FA</Button>
          </div>
        ) : setup ? (
          <div className="space-y-3 text-sm">
            <p>1. Scannez ce QR code avec Google Authenticator, Authy ou 1Password.</p>
            <div className="inline-block rounded border p-3"><QRCodeSVG value={setup.otpauth_uri} size={160} /></div>
            <p className="break-all text-xs text-slate-400">Ou saisissez la clé : {setup.secret}</p>
            <p>2. Entrez le code à 6 chiffres affiché :</p>
            <input inputMode="numeric" maxLength={6} placeholder="000000" value={code} onChange={(e) => setCode(e.target.value)} />
            <ErrorMsg error={enable.error} />
            <Button onClick={() => enable.mutate()}>Activer</Button>
          </div>
        ) : (
          <div className="space-y-3"><p className="text-sm text-slate-600">Protège votre compte même si votre mot de passe est volé. <b>Fortement recommandé.</b></p><Button onClick={() => start.mutate()}>Activer la 2FA</Button></div>
        )}
      </Card>
      <Card title="Changer mon mot de passe">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); change.mutate(); }}>
          <Field label="Mot de passe actuel"><input type="password" autoComplete="current-password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label="Nouveau mot de passe" hint="12 caractères minimum"><input type="password" autoComplete="new-password" minLength={12} required value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          <ErrorMsg error={change.error} />
          {pwMsg && <p className="text-sm text-emerald-700">{pwMsg}</p>}
          <Button type="submit" busy={change.isPending}>Modifier</Button>
        </form>
      </Card>
    </div>
  );
}

interface UserRow { id: number; email: string; name: string; role: string; totp_enabled: boolean }
function Users({ me }: { me: User }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", name: "", password: "", role: "member" });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/users") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api<{ ts: string; user: string; action: string; detail: string }[]>("/users/audit/log") });
  const create = useMutation({ mutationFn: () => api("/users", "POST", f), onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); setOpen(false); setF({ email: "", name: "", password: "", role: "member" }); } });
  const del = useMutation({ mutationFn: (id: number) => api(`/users/${id}`, "DELETE"), onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  return (
    <div className="space-y-6">
      <Card title="Utilisateurs" action={<Button variant="soft" onClick={() => setOpen(true)}>+ Utilisateur</Button>}>
        <ul className="divide-y divide-slate-100">
          {users.data?.map((u) => (
            <li key={u.id} className="flex items-center justify-between py-2.5 text-sm">
              <Link to={`/profil/${u.id}`} className="hover:text-brand-600">{u.name || u.email} <span className="text-slate-400">{u.email}</span></Link>
              <span className="flex items-center gap-3"><Badge tone={u.role === "admin" ? "blue" : u.role === "manager" ? "amber" : "slate"}>{u.role === "admin" ? "Admin" : u.role === "manager" ? "Manager" : "Membre"}</Badge>{u.totp_enabled && <Badge tone="green">2FA</Badge>}
                {u.id !== me.id && <button className="text-xs text-red-600" onClick={() => confirm(`Supprimer ${u.email} ?`) && del.mutate(u.id)}>Supprimer</button>}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Journal d'activité (200 derniers évènements)">
        <div className="max-h-72 overflow-y-auto text-xs">
          <table className="w-full"><tbody className="divide-y divide-slate-100">
            {audit.data?.map((a, i) => <tr key={i}><td className="py-1.5 pr-3 text-slate-400">{fmtDateTime(a.ts)}</td><td className="pr-3">{a.user}</td><td className="pr-3 font-medium">{a.action}</td><td className="text-slate-500">{a.detail}</td></tr>)}
          </tbody></table>
        </div>
      </Card>
      {open && (
        <Modal title="Nouvel utilisateur" onClose={() => setOpen(false)}>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <Field label="E-mail"><input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Nom"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Mot de passe provisoire" hint="12 caractères minimum"><input type="password" minLength={12} required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            <Field label="Rôle"><select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="member">Membre (CRM, tâches, temps)</option><option value="manager">Manager (+ finances, équipe, documents)</option><option value="admin">Administrateur (+ réglages, utilisateurs)</option></select></Field>
            <ErrorMsg error={create.error} />
            <div className="flex justify-end"><Button type="submit" busy={create.isPending}>Créer</Button></div>
          </form>
        </Modal>
      )}
    </div>
  );
}

export default function Settings({ user }: { user: User }) {
  const admin = user.role === "admin";
  const tabs = [["securite", "Mon compte & sécurité"], ...(admin ? [["integrations", "Intégrations"], ["users", "Utilisateurs"]] : [])] as const;
  const [tab, setTab] = useState<string>("securite");
  return (
    <>
      <PageHeader title="Paramètres" subtitle="Connexions aux services, sécurité du compte et utilisateurs." />
      <div data-tour="settings-tabs" className="mb-6 flex gap-1 overflow-x-auto border-b border-slate-200 sm:gap-2">
        {tabs.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium sm:px-4 ${tab === k ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{label}</button>
        ))}
      </div>
      {tab === "securite" && <Security user={user} />}
      {tab === "integrations" && admin && <Integrations />}
      {tab === "users" && admin && <Users me={user} />}
    </>
  );
}
