import { Row } from "../../api";
import { FieldDef } from "../../components";

export const KINDS: [string, string][] = [["prospect", "Prospect"], ["client", "Client"], ["supplier", "Fournisseur"], ["partner", "Partenaire"]];
export const kindLabel = (k: string) => KINDS.find(([v]) => v === k)?.[1] ?? k;
export const kindTone = (k: string) => (k === "client" ? "green" : k === "prospect" ? "blue" : "slate") as "green" | "blue" | "slate";

export const STAGES: { key: string; label: string; tone: string }[] = [
  { key: "prospect", label: "Prospect", tone: "border-slate-300" },
  { key: "contact", label: "Contact établi", tone: "border-sky-400" },
  { key: "quote", label: "Devis envoyé", tone: "border-amber-400" },
  { key: "negotiation", label: "Négociation", tone: "border-violet-400" },
  { key: "won", label: "Gagné ✅", tone: "border-emerald-500" },
  { key: "lost", label: "Perdu", tone: "border-red-300" },
];

export const companyRef = { endpoint: "/crm/companies", label: (r: Row) => r.name };
export const contactRef = { endpoint: "/crm/contacts", label: (r: Row) => `${r.first_name} ${r.last_name}`.trim() || r.email };

export const companyFields: FieldDef[] = [
  { name: "name", label: "Nom de la société", required: true },
  { name: "kind", label: "Type", type: "select", options: KINDS },
  { name: "siret", label: "SIRET" },
  { name: "vat_number", label: "N° TVA intracom." },
  { name: "website", label: "Site web" },
  { name: "sector", label: "Secteur d'activité" },
  { name: "email", label: "E-mail général", type: "email" },
  { name: "phone", label: "Téléphone" },
  { name: "address", label: "Adresse", wide: true },
  { name: "postal_code", label: "Code postal" },
  { name: "city", label: "Ville" },
  { name: "country", label: "Pays" },
  { name: "tags", label: "Étiquettes", hint: "Séparées par des virgules : vip, formation…" },
  { name: "notes", label: "Notes", type: "textarea" },
];

export const contactFields: FieldDef[] = [
  { name: "first_name", label: "Prénom" },
  { name: "last_name", label: "Nom", required: true },
  { name: "company_id", label: "Société", type: "ref", ref: companyRef },
  { name: "job_title", label: "Poste" },
  { name: "email", label: "E-mail", type: "email" },
  { name: "phone", label: "Téléphone" },
  { name: "tags", label: "Étiquettes" },
  { name: "notes", label: "Notes", type: "textarea" },
];

export const oppFields: FieldDef[] = [
  { name: "title", label: "Intitulé de l'affaire", required: true, wide: true },
  { name: "company_id", label: "Société", type: "ref", ref: companyRef },
  { name: "contact_id", label: "Contact", type: "ref", ref: contactRef },
  { name: "stage", label: "Étape", type: "select", options: STAGES.map((s) => [s.key, s.label] as [string, string]) },
  { name: "amount", label: "Montant estimé (€ HT)", type: "number" },
  { name: "probability", label: "Probabilité (%)", type: "number", step: "5" },
  { name: "expected_close", label: "Clôture prévue", type: "date" },
  { name: "owner_email", label: "Responsable (e-mail)", type: "email" },
  { name: "next_action", label: "Prochaine action", wide: true },
  { name: "notes", label: "Notes", type: "textarea" },
];

export const taskFields: FieldDef[] = [
  { name: "title", label: "Tâche", required: true, wide: true },
  { name: "due_date", label: "Échéance", type: "date" },
  { name: "assignee_email", label: "Responsable (e-mail)", type: "email" },
  { name: "company_id", label: "Société", type: "ref", ref: companyRef },
  { name: "contact_id", label: "Contact", type: "ref", ref: contactRef },
  { name: "notes", label: "Notes", type: "textarea" },
];
