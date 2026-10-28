import { useEffect, useState } from "react";
import { api } from "../../api";
import { Badge, cx } from "../../ui";

interface Hit {
  label: string;
  siren: string;
  active: boolean;
  legal_form: string;
  fields: Record<string, string>;
}

/** Recherche dans l'annuaire public des entreprises : choisir un résultat remplit la fiche « Société ». */
export function CompanyLookup({ onPick, syncName = true }: { onPick: (values: Record<string, unknown>) => void; syncName?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState("");

  useEffect(() => {
    const term = q.trim();
    if (term.length < 3 || term === picked) {
      setHits([]);
      return;
    }
    setBusy(true);
    setError("");
    const t = setTimeout(() => {
      api<Hit[]>(`/crm/companies/lookup?q=${encodeURIComponent(term)}`)
        .then(setHits)
        .catch((e) => {
          setHits([]);
          setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => setBusy(false));
    }, 400);
    return () => clearTimeout(t);
  }, [q, picked]);

  const pick = (h: Hit) => {
    // On ne remplace que par des valeurs connues : un champ vide de l'annuaire n'efface pas la saisie.
    onPick(Object.fromEntries(Object.entries(h.fields).filter(([, v]) => v)));
    setPicked(h.fields.name);
    setQ(h.fields.name);
    setHits([]);
  };

  return (
    <div className="rounded border border-brand-600/30 bg-brand-50/40 p-3">
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-slate-700">Rechercher l'entreprise (nom, SIREN ou SIRET)</span>
        <input
          autoFocus
          placeholder="Ex : Formasyl, 552120222…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPicked("");
            // À la création, ce que l'on tape sert aussi de nom (sauf un SIREN/SIRET en chiffres).
            if (syncName && !/^[\d\s]*$/.test(e.target.value)) onPick({ name: e.target.value });
          }}
        />
      </label>
      <p className="mt-1 text-xs text-slate-500">
        {busy ? "Recherche dans l'annuaire des entreprises…" : picked ? "Fiche pré-remplie : vérifiez puis enregistrez." : "Choisissez un résultat pour remplir automatiquement SIRET, TVA, adresse et activité."}
      </p>
      {error && <p className="mt-1 text-xs text-red-700">{error}</p>}
      {hits.length > 0 && (
        <ul className="mt-2 max-h-64 divide-y divide-slate-200 overflow-y-auto rounded border border-slate-300 bg-white">
          {hits.map((h) => (
            <li key={h.siren || h.label}>
              <button type="button" onClick={() => pick(h)} className={cx("w-full px-3 py-2 text-left text-sm hover:bg-brand-50", !h.active && "opacity-60")}>
                <span className="flex items-center gap-2 font-medium text-slate-900">
                  {h.label}
                  {!h.active && <Badge tone="red">Fermée</Badge>}
                </span>
                <span className="block text-xs text-slate-500">
                  {[h.fields.city, h.fields.postal_code, h.legal_form, h.siren && `SIREN ${h.siren}`].filter(Boolean).join(" · ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!busy && !error && q.trim().length >= 3 && !picked && hits.length === 0 && (
        <p className="mt-1 text-xs text-slate-500">Aucune entreprise trouvée : remplissez la fiche à la main.</p>
      )}
    </div>
  );
}
