"""Standardized municipality and barangay options for Laguna coverage."""

from flask import has_app_context
from sqlalchemy import inspect

from app.extensions import db

MUNICIPALITY_BARANGAYS = {
    "Santa Maria": [
        "Adia",
        "Bagong Pook",
        "Bagumbayan",
        "Bubukal",
        "Cabooan",
        "Calangay",
        "Cambuja",
        "Coralan",
        "Cueva",
        "Inayapan",
        "Jose Laurel Sr.",
        "Jose Rizal",
        "Kayhakat",
        "Macasipac",
        "Masinao",
        "Mataling-Ting",
        "Pao-o",
        "Parang ng Buho",
        "Poblacion I",
        "Poblacion II",
        "Poblacion III",
        "Poblacion IV",
        "Santiago",
        "Talangka",
        "Tungkod",
    ],
    "Siniloan": [
        "Acevida",
        "Bagong Pag-Asa",
        "Bagumbarangay",
        "Buhay",
        "Gen. Luna",
        "G. Redor",
        "Halayhayin",
        "J. Rizal",
        "Kapatalan",
        "Laguio",
        "Liyang",
        "Llavac",
        "Macatad",
        "Magsaysay",
        "Mayatba",
        "Mendiola",
        "P. Burgos",
        "Pandeno",
        "Salubungan",
        "Wawa",
    ],
    "Famy": [
        "Asana",
        "Bacong-Sigsigan",
        "Bagong Pag-Asa",
        "Balitoc",
        "Banaba",
        "Batuhan",
        "Bulihan",
        "Caballero",
        "Calumpang",
        "Cuebang Bato",
        "Damayan",
        "Kapatalan",
        "Kataypuanan",
        "Liyang",
        "Maate",
        "Mayatba",
        "Minayutan",
        "Salangbato",
        "Tunhac",
    ],
    "Pakil": [
        "Banilan",
        "Bano",
        "Burgos",
        "Casa Real",
        "Casinsin",
        "Dorado",
        "Gonzales",
        "Kabulusan",
        "Matikiw",
        "Rizal",
        "Saray",
        "Taft",
        "Tavera",
    ],
    "Pangil": [
        "Balian",
        "Dambo",
        "Galalan",
        "Isla",
        "Mabato-Asufre",
        "Natividad",
        "San Jose",
        "Sulib",
    ],
    "Mabitac": [
        "Amuyong",
        "Bayanihan",
        "Lambac",
        "Libis ng Nayon",
        "Lucong",
        "Maligaya",
        "Masikap",
        "Matalatala",
        "Nanguma",
        "Numero",
        "Paagahan",
        "Pag-Asa",
        "San Antonio",
        "San Miguel",
        "Sinagtala",
    ],
    "Kalayaan": [
        "Longos",
        "San Antonio",
        "San Juan",
    ],
    "Paete": [
        "Ibaba del Sur",
        "Maytoong",
        "Ermita",
        "Quinale",
        "Ilaya del Sur",
        "Ilaya del Norte",
        "Bagumbayan",
        "Bangkusay",
        "Ibaba del Norte",
    ],
}


def get_municipalities():
    db_municipalities = _get_municipalities_from_db()
    if db_municipalities:
        return db_municipalities
    return list(MUNICIPALITY_BARANGAYS.keys())


def _get_municipalities_from_db():
    if not has_app_context():
        return []

    try:
        if 'municipalities' not in inspect(db.engine).get_table_names():
            return []

        from app.models import Municipality

        return [
            row[0]
            for row in db.session.query(Municipality.name)
            .filter(Municipality.name.isnot(None))
            .order_by(Municipality.name)
            .all()
            if row[0]
        ]
    except Exception:
        return []


def get_barangays_by_municipality(municipality):
    if municipality in MUNICIPALITY_BARANGAYS:
        return MUNICIPALITY_BARANGAYS.get(municipality, [])

    # For custom municipalities, infer known barangays from existing user profiles.
    if has_app_context():
        try:
            from app.models import CommunityUsers

            rows = db.session.query(CommunityUsers.barangay).filter(
                CommunityUsers.municipality == municipality,
                CommunityUsers.barangay.isnot(None),
                CommunityUsers.barangay != '',
            ).distinct().all()
            return sorted({row[0] for row in rows if row[0]})
        except Exception:
            return []

    return []


def is_valid_municipality(municipality):
    return municipality in get_municipalities()


def is_valid_barangay(municipality, barangay):
    if municipality in MUNICIPALITY_BARANGAYS:
        return barangay in MUNICIPALITY_BARANGAYS[municipality]

    # Allow non-empty barangays for custom municipalities without a canonical list.
    return bool((barangay or '').strip())
