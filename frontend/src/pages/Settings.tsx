import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { Field as IField, User, api } from "../api";
import { Badge, Button, Card, ErrorMsg, Field, Loading, Modal, PageHeader, fmtDateTime } from "../ui";

const GROUPS: Record<string, { title: string; test?: string; intro: string }> = {
  company: { title: "Ma société (devis & factures)", intro: "Ces informations apparaissent sur vos PDF de devis et factures. Pensez à les compléter avant d'émettre votre première facture. Guide : section 8." },
  outlook: { title: "Outlook (Microsoft 365)", test: "outlook", intro: "Pour lire les mails. Guide : docs/CONFIGURATION.md, section 3." },
  google: { title: "Google (notes de frais en PDF)", test: "google", intro: "Pour remplir le modèle Google Doc et en faire un PDF. Guide : section 4." },
  email: { title: "E-mail d'envoi des alertes (SMTP)", test: "smtp", intro: "Pour recevoir les alertes par e-mail. Guide : section 5." },
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
        <Button variant="ghost" type="button" busy={save.isPending} disabled={f.secret && !v && !f.is_set} onClick={() => save.mutate()}>{saved ? "✔" : f.secret && !v && f.is_set ? "Effacer" : "OK"}</Button>
      </div>
    </Field>
  );
}

function Integrations() {
  const [result, setResult] = useState<Record<string, string>>({});
  const { data } = useQuery({ queryKey: ["integrations"], queryFn: () => api<IField[]>("/integrations") });
  const test = useMutation({
    mutationFn: (s: string) => api<{ message: string }>(`/integrations/test/${s}`, "POST"),
    onSuccess: (r, s) => setResult((x) => ({ ...x, [s]: `✅ ${r.message}` })),
    onError: (e, s) => setResult((x) => ({ ...x, [s]: `❌ ${e instanceof Error ? e.message : e}` })),
  });
  if (!data) return <Loading />;
  return (
    <div className="space-y-6">
      {Object.entries(GROUPS).map(([g, meta]) => (
        <Card key={g} title={meta.title} action={meta.test && <Button variant="soft" busy={test.isPending && test.variables === meta.test} onClick={() => test.mutate(meta.test!)}>Tester la connexion</Button>}>
          <p className="mb-4 text-xs text-slate-400">{meta.intro}</p>
          {meta.test && result[meta.test] && <p className="mb-4 text-sm">{result[meta.test]}</p>}
          <div className="grid gap-4 sm:grid-cols-2">
            {data.filter((f) => f.group === g).map((f) => <div key={f.key} className={f.multiline ? "sm:col-span-2" : ""}><IntegrationField f={f} /></div>)}
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
  const change = useMutation({ mutationFn: () => api("/auth/password", "POST", pw), onSuccess: () => { setPwMsg("✅ Mot de passe modifié"); setPw({ current_password: "", new_password: "" }); }, onError: () => setPwMsg("") });
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
            <div className="inline-block rounded-lg border p-3"><QRCodeSVG value={setup.otpauth_uri} size={160} /></div>
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
              <span>{u.name || u.email} <span className="text-slate-400">{u.email}</span></span>
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
            <Field label="Rôle"><select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="member">Membre (CRM, tâches, temps, congés)</option><option value="manager">Manager (+ finances, équipe, documents)</option><option value="admin">Administrateur (+ réglages, utilisateurs)</option></select></Field>
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
      <div className="mb-6 flex gap-2 border-b border-slate-200">
        {tabs.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === k ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{label}</button>
        ))}
      </div>
      {tab === "securite" && <Security user={user} />}
      {tab === "integrations" && admin && <Integrations />}
      {tab === "users" && admin && <Users me={user} />}
    </>
  );
}
