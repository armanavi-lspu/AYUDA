"""Standardized municipality and barangay options for Laguna coverage."""

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
    return list(MUNICIPALITY_BARANGAYS.keys())


def get_barangays_by_municipality(municipality):
    return MUNICIPALITY_BARANGAYS.get(municipality, [])


def is_valid_municipality(municipality):
    return municipality in MUNICIPALITY_BARANGAYS


def is_valid_barangay(municipality, barangay):
    if municipality not in MUNICIPALITY_BARANGAYS:
        return False
    return barangay in MUNICIPALITY_BARANGAYS[municipality]
