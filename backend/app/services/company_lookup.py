"""Recherche d'une entreprise dans l'annuaire public (API Recherche d'entreprises, data.gouv.fr).

Gratuit, sans clé : https://recherche-entreprises.api.gouv.fr — on renvoie des champs déjà au format
du formulaire « Société » du CRM, pour pré-remplir la fiche à partir du nom, du SIREN ou du SIRET.
"""

import time
from typing import Any

import httpx

API_URL = "https://recherche-entreprises.api.gouv.fr/search"
CACHE_TTL = 600
_cache: dict[str, tuple[float, list[dict]]] = {}


class CompanyLookupError(RuntimeError):
    """L'annuaire est injoignable ou a répondu une erreur."""


# Formes juridiques les plus courantes (codes INSEE « catégorie juridique »)
LEGAL_FORMS = {
    "1000": "Entrepreneur individuel",
    "5410": "SARL nationale",
    "5498": "EURL",
    "5499": "SARL",
    "5505": "SA à conseil d'administration",
    "5599": "SA",
    "5710": "SAS",
    "5720": "SASU",
    "5485": "SELARL",
    "6540": "SCI",
    "6599": "Société civile",
    "9220": "Association déclarée",
}

# Sections de la nomenclature NAF : donne un libellé lisible au code d'activité
NAF_SECTIONS = {
    "A": "Agriculture, sylviculture et pêche",
    "B": "Industries extractives",
    "C": "Industrie manufacturière",
    "D": "Énergie",
    "E": "Eau, déchets, dépollution",
    "F": "Construction",
    "G": "Commerce",
    "H": "Transports et entreposage",
    "I": "Hébergement et restauration",
    "J": "Information et communication",
    "K": "Activités financières et d'assurance",
    "L": "Activités immobilières",
    "M": "Activités spécialisées, scientifiques et techniques",
    "N": "Services administratifs et de soutien",
    "O": "Administration publique",
    "P": "Enseignement",
    "Q": "Santé humaine et action sociale",
    "R": "Arts, spectacles et activités récréatives",
    "S": "Autres activités de services",
    "T": "Activités des ménages",
    "U": "Activités extra-territoriales",
}

EMPLOYEES = {
    "NN": "non renseigné",
    "00": "0 salarié",
    "01": "1 à 2 salariés",
    "02": "3 à 5 salariés",
    "03": "6 à 9 salariés",
    "11": "10 à 19 salariés",
    "12": "20 à 49 salariés",
    "21": "50 à 99 salariés",
    "22": "100 à 199 salariés",
    "31": "200 à 249 salariés",
    "32": "250 à 499 salariés",
    "41": "500 à 999 salariés",
    "42": "1 000 à 1 999 salariés",
    "51": "2 000 à 4 999 salariés",
    "52": "5 000 à 9 999 salariés",
    "53": "10 000 salariés et plus",
}


def vat_number(siren: str) -> str:
    """Numéro de TVA intracommunautaire français, calculé à partir du SIREN."""
    if not (siren and siren.isdigit() and len(siren) == 9):
        return ""
    key = (12 + 3 * (int(siren) % 97)) % 97
    return f"FR{key:02d}{siren}"


def _street(siege: dict[str, Any]) -> str:
    """Adresse sans le code postal ni la ville (déjà dans leurs propres champs)."""
    parts = [siege.get(k) for k in ("numero_voie", "indice_repetition", "type_voie", "libelle_voie")]
    street = " ".join(str(p) for p in parts if p)
    if siege.get("complement_adresse"):
        street = f"{siege['complement_adresse']}, {street}" if street else siege["complement_adresse"]
    if street:
        return street.strip()
    full = (siege.get("adresse") or "").strip()  # repli : « 10 RUE X 75001 PARIS »
    tail = f"{siege.get('code_postal') or ''} {siege.get('libelle_commune') or ''}".strip()
    return full[: -len(tail)].strip(" ,") if tail and full.endswith(tail) else full


def normalize(item: dict[str, Any]) -> dict[str, Any]:
    siege = item.get("siege") or {}
    siren = str(item.get("siren") or "")
    naf = item.get("activite_principale") or siege.get("activite_principale") or ""
    section = NAF_SECTIONS.get(item.get("section_activite_principale") or "", "")
    sector = f"{section} ({naf})" if section and naf else section or naf
    legal_form = LEGAL_FORMS.get(str(item.get("nature_juridique") or ""), "")
    leaders = []
    for d in (item.get("dirigeants") or [])[:3]:
        name = " ".join(x for x in (d.get("prenoms"), d.get("nom")) if x) or d.get("denomination") or ""
        if name:
            leaders.append(f"{name.title()} ({d['qualite']})" if d.get("qualite") else name.title())

    notes = []
    if legal_form:
        notes.append(f"Forme juridique : {legal_form}")
    if leaders:
        notes.append("Dirigeant(s) : " + ", ".join(leaders))
    if item.get("date_creation"):
        notes.append(f"Création : {item['date_creation']}")
    if (eff := EMPLOYEES.get(str(item.get("tranche_effectif_salarie") or ""))) and eff != "non renseigné":
        notes.append(f"Effectif : {eff}")

    active = (item.get("etat_administratif") or siege.get("etat_administratif") or "A") == "A"
    return {
        "siren": siren,
        "active": active,
        "legal_form": legal_form,
        "leaders": leaders,
        # Champs prêts à injecter tels quels dans le formulaire « Société »
        "fields": {
            "name": (item.get("nom_raison_sociale") or item.get("nom_complet") or "").strip(),
            "siret": str(siege.get("siret") or ""),
            "vat_number": vat_number(siren),
            "sector": sector,
            "address": _street(siege),
            "postal_code": str(siege.get("code_postal") or ""),
            "city": (siege.get("libelle_commune") or "").title(),
            "country": "France",
            "notes": "\n".join(notes),
        },
        "label": item.get("nom_complet") or item.get("nom_raison_sociale") or siren,
    }


def search(query: str, limit: int = 6, client: httpx.Client | None = None) -> list[dict]:
    q = " ".join(query.split())[:100]
    if len(q) < 3:
        return []
    key = f"{q.lower()}|{limit}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    try:
        http = client or httpx.Client(timeout=8)
        r = http.get(
            API_URL, params={"q": q, "per_page": limit, "page": 1}, headers={"Accept": "application/json"}
        )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CompanyLookupError(
            "L'annuaire des entreprises est momentanément injoignable. Réessayez ou remplissez à la main."
        ) from exc
    finally:
        if client is None:
            http.close()
    results = [normalize(item) for item in (data.get("results") or [])[:limit]]
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = (time.monotonic(), results)
    return results
