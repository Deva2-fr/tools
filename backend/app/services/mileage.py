"""Indemnités kilométriques : barème fiscal (tranche jusqu'à 5 000 km par an) et calcul d'une note.

Barème 2024, reconduit en 2025 : à mettre à jour ici quand l'administration en publie un nouveau.
Le taux appliqué est gardé sur chaque note, donc un changement ne modifie pas les notes passées.
"""

CATEGORY = "Indemnités kilométriques"
ELECTRIC_BONUS = 0.20  # véhicules 100 % électriques : +20 %

# (CV minimum, € / km) par type de véhicule, du plus puissant au moins puissant.
RATES = {
    "car": [(7, 0.697), (6, 0.665), (5, 0.636), (4, 0.606), (0, 0.529)],
    "moto": [(6, 0.606), (3, 0.468), (0, 0.395)],
}
LABELS = {"car": "Voiture", "moto": "Moto (> 50 cm³)"}


def base_rate(vehicle_type: str, fiscal_hp: int, electric: bool = False) -> float:
    table = RATES.get(vehicle_type, RATES["car"])
    rate = next(r for hp, r in table if fiscal_hp >= hp)
    return round(rate * (1 + ELECTRIC_BONUS), 3) if electric else rate


def total_km(distance_km: float, round_trip: bool, trips: int) -> float:
    return round(distance_km * (2 if round_trip else 1) * max(trips, 1), 1)


def amount(km: float, rate: float) -> float:
    return round(km * rate, 2)


def rates_table() -> dict:
    """Barème pour l'interface (aperçu du calcul)."""
    return {
        "electric_bonus": ELECTRIC_BONUS,
        "vehicles": [
            {"type": t, "label": LABELS[t], "rates": [{"min_hp": hp, "rate": r} for hp, r in reversed(table)]}
            for t, table in RATES.items()
        ],
    }
