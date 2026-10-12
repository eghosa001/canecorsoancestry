"""Name-based BREEDING-KENNEL hypotheses learned from the 116,370-dog archive.

These recurring prefixes/suffixes were counted across the September 2026
CaneCorsoPedigree archive. They are NOT breeder registration evidence.
Nothing here grants ownership, verifies kennels, or authorizes dog edits.

The full archive analysis is maintained separately from the application.
A candidate may be displayed for expert review but must never be assigned
to a canonical Dog.kennel based solely on a name pattern.
"""
import re
import unicodedata

# position; archive dogs sharing this exact affix; observed phrase.
# This is a bounded, source-derived subset of 2,078 recurring affixes
# (>=8 occurrences, >=3 independent parent pairs) in 116,370 dog names.
_ARCHIVE_KENNEL_PATTERNS = """
S|1943|Dell'antico Cerberus
S|1604|Del Rosso Malpelo
S|916|Dei Martinotti
S|857|Della Porta Dipinta
P|828|Chiaro E Tondo
S|826|Di Castell'anselmo
S|731|Della Nevaia
S|585|Di Casa Cesaro
P|500|Campo Di Cavallo
S|485|Degli Elmi
S|445|Della Valle Dei Lord
S|430|Dei Molossi Dell'angra
P|417|Hägnatorpets
P|395|Bioynic's
S|386|Dei Negroni
S|367|Dell'impero Maya
S|350|Dei Corsi Della Valmorea
S|344|Dell'antiqua Apulia
S|315|Dei Paesi Bassi
S|315|Iz Dinastii Chempionov
S|297|Di Gran Burrone
S|293|Corso Di Munteanu
S|290|Custodi Nos
P|290|La Potenza E L'amore
S|273|Delle Principesse De I Giacchini
P|268|Rothorm Jy Dream
S|261|Del Murgese
S|257|Dei Grausi
S|249|Di Casa Latorre
S|248|Dei Conforti Di Savoia
S|231|Del Montagna Oro
P|222|Guardiano Degli Angeli
P|212|Saxellum
P|205|Alcor's
P|204|Stanley Pat
S|196|Dello Specchio Di Atlantide
S|190|Della Ruralis Gens
S|187|Del Taras Tarentum
S|180|Dei Volsci
S|177|Del Dyrium
S|175|Di Casa Mattia
S|174|Promessa Di Futuro
S|171|Sangue Magnifica
S|170|Dell'antica Borgata
S|164|Dei Molossi D'eburon
S|162|Di Paianello
S|147|La Grazia Di Dio
P|141|Castleguard
P|136|In Futuro
P|131|Maxento
S|130|Von Der Liebessphaere
P|128|Ollada Arlekin
P|127|El Mesquital
S|125|Dell'appio
P|120|Maximo's
S|119|Il Corso Dell'olimpo
S|117|Di Casa Fiamma
P|116|Bel Monte
S|113|Della Valle Degli Orsi Ali
P|110|Nochnoy Dozor
S|110|Dei Molossi Aretusei
S|105|Andrax Gold
P|104|Apriori Best
S|103|Dei Corsari Del Lido
S|102|De Finibus Terrae
S|101|Della Vigna Della Corte
P|99|Casa Guardie
S|96|Di Fosso Corno
P|93|Amico Della Gente
P|91|Force Pride
P|91|Moi Legioner
P|90|Kane Per La Vita
S|89|Dei Peligni
S|88|En Una Palabra
S|87|Dei Re Di Roma
S|85|Del Cane Club
S|84|Della Corte Degli Olmi
S|82|Corso Imperium
S|81|Dei Corsi Del Greppo
S|80|Di Typhon
P|80|Sforza
S|77|Star Dragon
S|77|Della Corte Degli Olivi
P|76|Avalanche's
P|74|Mad River's
S|72|De La Mirage De Torrellas
P|70|Solo Prima
P|69|Ivy League
P|66|Aquila Dorata
S|65|Corso Of Bajer
P|64|Majoshaza Reme
S|64|Iz Sozvezdiya Adomasa
S|61|Dei Corsi Di Regina Teodolinda
P|60|Rus Best Line
S|60|Guardiano Da Passione
P|59|White Paloma
S|58|Z Mazurskiego Edenu
S|56|Di Casa Leone
S|54|Custode Del Trono
S|54|Degli Orsi Ali
S|50|Di Casa Catamo
# Additional high-support affixes identified by joining the 2026 original
# pedigree archive against exact source IDs of 20,993 kennel-less canonical
# dogs (not inferred from a current owner or submitter).
P|283|Scandifio's
P|205|Alcor's
S|247|Dell'appio
P|120|Maximo's
S|136|Strajano
P|126|Delizioso
S|180|Dell'anteler
P|67|Timoniere
S|76|Soberon
S|78|Del-orte
P|73|Ekskljuziv-n
P|74|Windypine's
S|103|Dell'alumera
P|56|Linia Blours
P|55|Fior Di Ferro
P|13|Mar E Sol's
S|34|Di Spicciano
P|123|Proudness As
P|119|Magnuslunds
P|59|Uncle And Nephew's
S|84|Della Corte Degli Olmi
S|20|De La Rune De Dalle
S|30|Blekitna Przystan
P|77|Megale Hellas
S|68|Di Dracaryus
P|40|Imprezo Polaris
S|28|Iz Zolotogo Ventsa
S|113|Di Casa Leone
S|17|Z Lesnego Potoku
S|94|Del Diryo
S|72|Di Rio Nero
S|24|Des Dunes Des Sages
S|58|Della Scuderia De Angelis
P|15|Vento E Tempesta
P|68|Angelo Del Guardiano
S|124|Della Dorsale
P|18|Schaste Moe
S|75|Des Gardiens Des Murailles
S|33|De Genevayse
P|17|Master K9's
S|79|Du Nord
P|17|Grand Favourite
S|21|Des Pres De Couriere
S|94|Del Nero Velluto
S|13|Barbarian Corso
S|14|San Diego D W
P|25|Julia Cezaris
P|22|Borealis Rus
S|64|Del Giardino Delle Ombre
S|13|Do Casal Do Libro
S|11|Del Baki Casa
S|18|Lou Gardian Di Prouvenco
P|18|Sleeping Giants
S|16|Wise Keeper
P|16|Rimskyi Kvartal
""".strip()

_TOKEN_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


def name_tokens(value):
    """Normalize punctuation/case while keeping source names unchanged."""
    value = unicodedata.normalize("NFKC", value or "").casefold().replace("’", "'")
    return tuple(_TOKEN_RE.findall(value))


def _matched_position(haystack, needle):
    if not needle or len(haystack) <= len(needle):
        return None
    for i in range(len(haystack)-len(needle)+1):
        if haystack[i:i+len(needle)] == needle:
            return "prefix" if i == 0 else (
                "suffix" if i+len(needle) == len(haystack) else "middle"
            )
    return None


def archive_pattern_hints(dog_name, *, limit=3):
    """Return review-only hypotheses, never a verified or automatic link.

    Prefix/suffix evidence is stronger than an internal name component,
    but not conclusive. A long prefix can be a registered title or
    purchased dog designation rather than its original breeder.
    """
    tokens = name_tokens(dog_name)
    hits = []
    seen_source_rows = set()
    for row in _ARCHIVE_KENNEL_PATTERNS.splitlines():
        if not row or row.lstrip().startswith("#"):
            continue
        place, support, label = row.split("|", 2)
        source_key = (place, name_tokens(label))
        if source_key in seen_source_rows:
            continue
        seen_source_rows.add(source_key)
        name = name_tokens(label)
        observed = _matched_position(tokens, name)
        if observed is None:
            continue
        if (place == "P" and observed != "prefix") or (
            place == "S" and observed != "suffix"
        ):
            # An unexpected internal position is a weaker suggestion;
            # do not portray it as an archival anchored affix.
            continue
        hits.append({
            "label": label,
            "position": observed,
            "archive_name_count": int(support),
            "source": "116370_dog_archival_name_patterns",
            "certainty": "unverified_hypothesis",
            "score": len(name)*10 + min(int(support), 1000)/100,
        })
    hits.sort(key=lambda h: (-h["score"], -h["archive_name_count"], h["label"]))
    result = []
    for h in hits:
        nh = name_tokens(h["label"])
        if any(nh != name_tokens(prev["label"]) and nh in (
            name_tokens(prev["label"])[:len(nh)],
            name_tokens(prev["label"])[-len(nh):]
        ) for prev in result):
            continue
        result.append(h)
        if len(result) >= limit:
            break
    return result


def match_existing_kennel_name(dog_name, kennel_name):
    """Allow exact phrase matches at BEGINNING, MIDDLE or END of name.

    This is for a moderator-facing suggestion only; names alone are never
    grounds to update Dog.kennel.
    """
    name = name_tokens(kennel_name)
    if not name or (len(name) == 1 and len(name[0]) < 6):
        return None
    return _matched_position(name_tokens(dog_name), name)
