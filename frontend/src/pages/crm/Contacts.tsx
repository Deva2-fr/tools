import { Link } from "react-router-dom";
import { ResourcePage } from "../../components";
import { CsvImportButton } from "../../csvimport";
import { contactFields } from "./shared";

export default function Contacts() {
  return (
    <ResourcePage
      title="Contacts"
      subtitle="Les personnes avec qui vous travaillez. Leurs mails Outlook apparaissent sur la fiche de leur société."
      endpoint="/crm/contacts"
      newLabel="Nouveau contact"
      exportName="contacts"
      fields={contactFields}
      empty="Aucun contact. Ajoutez-en un ou importez un fichier CSV."
      headerExtra={<div className="mb-4 flex justify-end"><CsvImportButton endpoint="/crm/contacts/import" hint="Colonnes : first_name, last_name, email, phone, job_title, company_id, tags, notes. Les e-mails déjà présents sont ignorés." /></div>}
      columns={[
        { label: "Nom", render: (r) => <span className="font-medium">{`${r.first_name} ${r.last_name}`.trim() || "—"}</span> },
        { label: "Poste", render: (r) => r.job_title || "—" },
        { label: "E-mail", render: (r) => r.email ? <a className="text-brand-600" href={`mailto:${r.email}`}>{r.email}</a> : "—" },
        { label: "Téléphone", render: (r) => r.phone || "—" },
        { label: "Société", render: (r) => r.company_id ? <Link className="text-brand-600" to={`/crm/societes/${r.company_id}`}>Voir la fiche</Link> : "—" },
      ]}
    />
  );
}
