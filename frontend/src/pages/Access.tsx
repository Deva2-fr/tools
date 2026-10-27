import { Row } from "../api";
import { ResourcePage } from "../components";
import { Badge, fmtDate } from "../ui";

const due = (r: Row) => {
  if (!r.rotate_every_days) return null;
  if (!r.last_rotated) return "unknown";
  return (Date.now() - new Date(r.last_rotated).getTime()) / 864e5 > r.rotate_every_days ? "late" : "ok";
};

export default function Access() {
  return (
    <ResourcePage
      title="Registre des accès"
      subtitle="Qui a accès à quoi, et où se trouve le mot de passe. ⚠️ N'écrivez JAMAIS un mot de passe ici : indiquez seulement son emplacement (ex : « Bitwarden > Deva2 > OVH »)."
      endpoint="/access" newLabel="Nouvel accès" exportName="acces"
      initial={{ rotate_every_days: 365 }}
      empty="Listez vos accès critiques : hébergeur, registrar, GitHub, banque, Google Workspace…"
      fields={[
        { name: "system", label: "Service / outil", required: true, hint: "OVH, GitHub, Qonto, Google Workspace…" },
        { name: "account", label: "Compte / identifiant", hint: "L'e-mail ou le nom d'utilisateur (pas le mot de passe)" },
        { name: "secret_location", label: "Où est le mot de passe ?", wide: true, hint: "Ex : Bitwarden > Deva2 > OVH" },
        { name: "holders", label: "Qui a accès ?", hint: "Prénoms séparés par des virgules" },
        { name: "last_rotated", label: "Dernier changement du mot de passe", type: "date" },
        { name: "rotate_every_days", label: "À changer tous les … jours (0 = jamais)", type: "number", step: "1" },
        { name: "notes", label: "Notes", type: "textarea" },
      ]}
      columns={[
        { label: "Service", render: (r) => <span className="font-medium">{r.system}</span> },
        { label: "Compte", render: (r) => r.account || "—" },
        { label: "Emplacement du secret", render: (r) => r.secret_location || <Badge tone="amber">Non renseigné</Badge> },
        { label: "Accès", render: (r) => r.holders || "—" },
        { label: "Rotation", render: (r) => { const s = due(r); return s === "late" ? <Badge tone="red">À changer ({fmtDate(r.last_rotated)})</Badge> : s === "unknown" ? <Badge tone="amber">Date inconnue</Badge> : s === "ok" ? <Badge tone="green">À jour</Badge> : "—"; } },
      ]}
    />
  );
}
