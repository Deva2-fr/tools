import httpx
import pytest

from app.services import company_lookup

SAMPLE = {
    "results": [
        {
            "siren": "552120222",
            "nom_complet": "SOCIETE GENERALE (SG)",
            "nom_raison_sociale": "SOCIETE GENERALE",
            "nature_juridique": "5599",
            "activite_principale": "64.19Z",
            "section_activite_principale": "K",
            "date_creation": "1864-05-04",
            "tranche_effectif_salarie": "53",
            "etat_administratif": "A",
            "siege": {
                "siret": "55212022200013",
                "numero_voie": "29",
                "type_voie": "BD",
                "libelle_voie": "HAUSSMANN",
                "code_postal": "75009",
                "libelle_commune": "PARIS",
                "adresse": "29 BD HAUSSMANN 75009 PARIS",
                "etat_administratif": "A",
            },
            "dirigeants": [{"nom": "DUPONT", "prenoms": "JEAN", "qualite": "Directeur général"}],
        },
        {"siren": "123", "nom_complet": "ENTREPRISE FERMEE", "etat_administratif": "C", "siege": {}},
    ]
}


def fake_client(payload=SAMPLE, status=200, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clear_cache():
    company_lookup._cache.clear()


def test_vat_number_matches_known_value():
    assert company_lookup.vat_number("552120222") == "FR27552120222"  # Société Générale
    assert company_lookup.vat_number("12") == "" and company_lookup.vat_number("") == ""


def test_normalize_fills_company_form_fields():
    r = company_lookup.search("societe generale", client=fake_client())
    f = r[0]["fields"]
    assert (
        f["name"] == "SOCIETE GENERALE"
        and f["siret"] == "55212022200013"
        and f["vat_number"] == "FR27552120222"
    )
    assert f["address"] == "29 BD HAUSSMANN" and f["postal_code"] == "75009" and f["city"] == "Paris"
    assert f["sector"] == "Activités financières et d'assurance (64.19Z)"
    assert "Forme juridique : SA" in f["notes"] and "Jean Dupont (Directeur général)" in f["notes"]
    assert r[0]["active"] is True and r[1]["active"] is False
    assert r[1]["fields"]["vat_number"] == ""  # SIREN invalide : pas de TVA inventée


def test_address_fallback_strips_postcode_and_city():
    siege = {"adresse": "10 RUE DE LA PAIX 75002 PARIS", "code_postal": "75002", "libelle_commune": "PARIS"}
    assert company_lookup._street(siege) == "10 RUE DE LA PAIX"


def test_short_query_does_not_call_api_and_results_are_cached():
    calls = []
    client = fake_client(calls=calls)
    assert company_lookup.search("ab", client=client) == []
    company_lookup.search("deva2", client=client)
    company_lookup.search("  DEVA2 ", client=client)
    assert len(calls) == 1 and calls[0].url.params["q"] == "deva2"


def test_api_error_becomes_friendly_error():
    with pytest.raises(company_lookup.CompanyLookupError):
        company_lookup.search("deva2", client=fake_client(status=503))


def test_lookup_endpoint(client, monkeypatch):
    monkeypatch.setattr(company_lookup, "search", lambda q: [{"label": q, "fields": {"name": q}}])
    assert client.get("/api/crm/companies/lookup?q=acme").json()[0]["fields"]["name"] == "acme"

    def boom(q):
        raise company_lookup.CompanyLookupError("injoignable")

    monkeypatch.setattr(company_lookup, "search", boom)
    r = client.get("/api/crm/companies/lookup?q=acme")
    assert r.status_code == 502 and r.json()["detail"] == "injoignable"


def test_lookup_requires_login(anon):
    assert anon.get("/api/crm/companies/lookup?q=acme").status_code == 401
