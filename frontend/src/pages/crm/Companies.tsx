import { Link } from "react-router-dom";
import { ResourcePage } from "../../components";
import { CsvImportButton } from "../../csvimport";
import { Badge } from "../../ui";
import { CompanyLookup } from "./CompanyLookup";
import { companyFields, kindLabel, kindTone } from "./shared";

export default function Companies() {
  return (
    <ResourcePage
      title="Sociétés"
      subtitle="Clients, prospects, fournisseurs et partenaires. Cliquez sur un nom pour voir toute la fiche."
      endpoint="/crm/companies"
      newLabel="Nouvelle société"
      exportName="societes"
      fields={companyFields}
      formTop={(patch) => <CompanyLookup onPick={patch} />}
      initial={{ kind: "prospect", country: "France" }}
      empty="Aucune société. Ajoutez-en une ou importez un fichier CSV."
      headerExtra={<div className="mb-4 flex justify-end"><CsvImportButton endpoint="/crm/companies/import" hint="Première ligne = en-têtes (name, kind, siret, vat_number, website, sector, email, phone, address, postal_code, city, country, tags, notes). Séparateur ; ou , . Les noms déjà présents sont ignorés." /></div>}
      columns={[
        { label: "Société", render: (r) => <Link className="font-medium text-brand-600" to={`/crm/societes/${r.id}`}>{r.name}</Link> },
        { label: "Type", render: (r) => <Badge tone={kindTone(r.kind)}>{kindLabel(r.kind)}</Badge> },
        { label: "Ville", render: (r) => r.city || "—" },
        { label: "Contact", render: (r) => <span className="text-slate-500">{r.email || r.phone || "—"}</span> },
        { label: "Étiquettes", render: (r) => r.tags ? r.tags.split(",").map((t: string) => <Badge key={t}>{t.trim()}</Badge>) : "—" },
      ]}
    />
  );
}
