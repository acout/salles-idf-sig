#!/usr/bin/env python3
"""
Extract venue metadata from batch_2.json entities.
Since the page content is minimal (just aggregator links), most fields will be null.
We extract what we can from entity metadata and the limited content.
"""
import json
import unicodedata

def normalize(s):
    """Normalize unicode for comparison: curly quotes -> straight, etc."""
    if s is None:
        return None
    # Replace curly quotes with straight
    s = s.replace('\u2019', "'").replace('\u2018', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    # NFKC normalize to handle composed/decomposed chars
    s = unicodedata.normalize('NFKC', s)
    return s

with open('batch_2.json') as f:
    data = json.load(f)

results = []

def infer_tags(name):
    """Infer activity tags from name."""
    tags = []
    name_lower = normalize(name).lower()
    tag_map = {
        'danse': ['danse moderne', 'danse orientale', 'danse classique', 'evjf', 'k-pop', 'kpop', 'dansé'],
        'yoga': ['yoga'],
        'pilates': ['pilate'],
        'arts_martiaux': ['self-defense', 'self-defense', 'boxe', 'ju-jitsu', 'jiu-jitsu', 'karate', 'karaté', 'penchak', 'silat'],
        'dojo': ['dojo'],
        'theatre': ['théâtre', 'theatre'],
        'musique': ['musique'],
        'coworking': ['coworking', 'bureau'],
        'conference': ['conférence', 'conference', 'réunion', 'reunion', 'séminaire', 'seminaire'],
        'evenement': ['événement', 'evenement', 'mariage'],
        'atelier': ['atelier', 'dessin', 'peinture', 'modelage', 'macramé', 'tricot'],
        'bien_etre': ['bien-être', 'relaxation', 'gym respiratoire'],
        'fitness': ['fitness', 'sport', 'gym', 'gymnastique'],
        'photo': ['photo', 'photographie'],
    }
    for tag, keywords in tag_map.items():
        if any(kw in name_lower for kw in keywords):
            tags.append(tag)
    return tags


def classify_entity(entity):
    """Determine is_actual_venue and related metadata."""
    raw_name = entity['canonical_name']
    name = normalize(raw_name)
    name_lower = name.lower()
    url = entity['official_website_url']
    url_lower = url.lower()
    
    is_actual = True
    venue_type = None
    rental_possible = "unclear"
    activity_tags = []
    venue_name_override = None
    
    # --- Names that are definitely NOT venues ---
    # Navigation/UI elements
    nav_ui = [
        "Consulter les tarifs", "Page load link", "Aller en haut", "Ecouter",
        "Blog", "Accueil", "accueil", "Réservation", "Règlement",
        "Réglement de Fonctionnement",
        "INSCRIPTION", "CONTACT", "Presse",
        "Voir le site internet", "Plus de réseaux sociaux",
        "Nous contacter", "Plan d'accès", "PLAN D'ACCES",
        "Présentation", "Actualités", "Planning",
        "Statuts de l'association", "Organigramme", "Mécénat",
        "Logo DOJO 5", "webmaster", "la rédaction",
        "06 63 70 30 15",
    ]
    # Normalize for comparison
    nav_ui_norm = [normalize(x) for x in nav_ui]
    
    if name in nav_ui_norm:
        return False, None, "unclear", [], None
    
    # Section/category pages
    section = [
        "Location salle", "Location de salles", "location",
        "Le camping", "Hébergements", "Alentours", "Fontainebleau",
        "Les espaces publics", "Espace seniors",
        "Nos salles à louer", "Infos pratiques",
        "Guide d'accès",
        "Où manger autour d'Espace Jules César ?",
        "Options et services complémentaires",
        "Associations", "Association", "Annuaire des associations",
        "service des associations",
        "Associations présentes", "Associations sportives",
        "Vie associative", "Activités",
        "Des îlots de fraîcheur et des espaces végétalisés",
        "Développement durable", "Compte association",
        "Location de salles Villejuif", "Location de salles à Villejuif 94800",
        "Location de salles autour de moi",
        "Caractéristiques et photos des studios ici",
        "MARIAGE",
        "Dans les maisons de quartier",
    ]
    section_norm = [normalize(x) for x in section]
    
    if name in section_norm:
        return False, None, "unclear", [], None
    
    # Course/activity pages
    courses = [
        "Cours de gym respiratoire", "Cours de K-Pop", "Cours de danse classique",
        "Cours enfants", "Eveil danse", "Eveil artistique",
        "Danse moderne contemporaine", "Danse orientale",
        "Self-défense", "Penchak Silat", "Boxe Anglaise", "Boxe Thaï",
        "Jiu-Jitsu Brésilien", "Karaté",
        "Dessin Peinture", "Pratiques créatives", "Photo",
        "Macramé", "Modelage", "Tricot",
        "Réserver son cours d'essai",
        "evjf/h dansé", "stages", "cours",
        "Tarifs",
    ]
    courses_norm = [normalize(x) for x in courses]
    
    if name in courses_norm:
        return False, 'studio_danse', "no", infer_tags(name), None
    
    # PDF forms and other non-venue docs
    if 'PDF' in name or 'pdf' in name:
        return False, None, "unclear", [], None
    
    # --- Site-specific classification ---
    
    # YMCA: organizational page, not a specific venue
    if 'ymcafrance.fr' in url or 'ymca-avignon.com' in url or 'ymca-paris.fr' in url:
        return False, None, "unclear", [], None
    
    # La Rivière Dorée: all sub-pages are sections, not individual venues
    if 'larivieredoree.com' in url:
        return False, 'centre_vacances', "yes", ['evenement', 'seminaire'], None
    
    # BCoworker: booking platform
    if 'bcoworker.com' in url:
        return False, None, "unclear", [], None
    
    # Les Mollières: municipal
    if 'lesmolieres.fr' in url:
        if name == "L'Espace culturel & associatif":
            return True, 'centre_culturel', "yes", ['evenement', 'conference'], "L'Espace culturel & associatif - Les Mollières"
        elif name == "Associations des Molieres":
            return False, None, "unclear", [], None
        else:
            return False, None, "unclear", [], None
    
    # Espace Jules César
    if 'espace-jules-cesar.fr' in url:
        jules_venues = {
            "Bureau individuel": ('coworking', 'yes', ['coworking', 'conference']),
            "Salle 2-8 personnes": ('salle', 'yes', ['conference', 'seminaire']),
        }
        jules_venues_norm = {normalize(k): v for k, v in jules_venues.items()}
        if name in jules_venues_norm:
            vt, rp, tags = jules_venues_norm[name]
            return True, vt, rp, tags, f"Espace Jules César - {raw_name}"
        return False, None, "unclear", [], None
    
    # Bagneux
    if 'bagneux92.fr' in url:
        return False, None, "unclear", [], None
    
    # Studio L'Envol: dance studio
    if 'studiolenvol.com' in url:
        if normalize(name) in [normalize("le studio")]:
            return True, 'studio_danse', "yes", ['danse'], "Studio L'Envol"
        elif normalize(name) in [normalize("location")]:
            return False, 'studio_danse', "yes", ['danse'], None
        elif normalize(name) in [normalize("accueil")]:
            return False, None, "unclear", [], None
        else:
            return False, 'studio_danse', "no", infer_tags(name), None
    
    # Association RDS
    if 'association-rds.com' in url:
        return False, 'studio_danse', "no", infer_tags(name), None
    
    # Arcueil
    if 'arcueil.fr' in url:
        arcueil_non_venues = [
            "Centres de santé", "Associations sportives",
            "Centres de protection maternelle et infantile",
            "Maîtrise de la population animale sur l'espace public",
            "Centre de santé Marcel Trigon",
            "Réclamation, intervention espaces verts", "Espaces verts",
        ]
        arcueil_non_venues_norm = [normalize(x) for x in arcueil_non_venues]
        if name in arcueil_non_venues_norm:
            return False, None, "unclear", [], None
        elif name == normalize("Espace 10-13"):
            return True, 'mairie', "unclear", ['conference'], None
        elif name == normalize("Centre Maï Politzer"):
            return True, 'mairie', "unclear", [], None
        elif name == normalize("Centre-Sud-Est"):
            return True, 'mairie', "unclear", [], None
        else:
            return False, None, "unclear", [], None
    
    # Bastide 95
    if 'bastide95.com' in url:
        if name == normalize("Salle Le Mas"):
            return True, 'salle_evenement', "yes", ['evenement', 'seminaire'], None
        elif name == normalize("Salle La Villa"):
            return True, 'salle_evenement', "yes", ['evenement', 'seminaire'], None
        elif "mariage" in name_lower:
            return False, 'salle_evenement', "yes", ['evenement'], None
        elif "Découvrir" in name or "découvrir" in name_lower:
            return False, None, "unclear", [], None
        else:
            return False, None, "unclear", [], None
    
    # Villejuif
    if 'villejuif.fr' in url:
        if name == normalize("Maisons de quartier"):
            return True, 'mairie', "unclear", ['conference'], None
        elif name == normalize("Centre-Sud-Est"):
            return True, 'mairie', "unclear", [], None
        else:
            return False, None, "unclear", [], None
    
    # Mappy (aggregator)
    if 'mappy.com' in url:
        return False, None, "unclear", [], None
    
    # Malakoff
    if 'malakoff.fr' in url:
        if name == normalize("Maisons de quartier"):
            return True, 'mairie', "unclear", ['conference'], None
        else:
            return False, None, "unclear", [], None
    
    # Dojo 5
    if 'dojo5.fr' in url:
        if name in [normalize("Tarifs"), normalize("Associations présentes"),
                    normalize("Logo DOJO 5"), normalize("Histoire de la salle"),
                    normalize("Mécénat")]:
            return False, None, "unclear", [], None
        elif name in [normalize("Réserver son cours d'essai")]:
            return False, 'dojo', "no", ['arts_martiaux'], None
        elif name in courses_norm:
            return False, 'dojo', "no", infer_tags(name), None
        else:
            return True, 'dojo', "unclear", ['arts_martiaux', 'dojo'], None
    
    # MJC La Châtre
    if 'mjcslachatre.jimdofree.com' in url:
        if name in [normalize("Vie associative"), normalize("Réglement de Fonctionnement"),
                    normalize("Statuts de l'association"), normalize("Organigramme"),
                    normalize("Mécénat"), normalize("Activités")]:
            return False, None, "unclear", [], None
        elif name in courses_norm:
            return False, 'mjc', "no", infer_tags(name), None
        else:
            return True, 'mjc', "unclear", infer_tags(name), None
    
    # Bourg-la-Reine
    if 'bourg-la-reine.fr' in url:
        if name == normalize("Maison des associations de la transition (MAT)"):
            return True, 'mairie', "unclear", ['conference'], "Maison des associations de la transition (MAT) - Bourg-la-Reine"
        else:
            return False, None, "unclear", [], None
    
    # Readspeaker / Google Forms (tools, not venues)
    if 'readspeaker.com' in url or 'forms.gle' in url:
        return False, None, "unclear", [], None
    
    # --- Generic name-based fallback if no site matched ---
    if venue_type is None and is_actual:
        # Catch any remaining names that are clearly non-venue
        remaining_non_venue = [
            "Guide d'accès", "Consulter la fiche détaillée",
        ]
        remaining_norm = [normalize(x) for x in remaining_non_venue]
        if name in remaining_norm:
            return False, None, "unclear", [], None
        
        # Pattern-based type inference
        if 'salle' in name_lower:
            venue_type = 'salle'
        elif 'dojo' in name_lower:
            venue_type = 'dojo'
        elif 'studio' in name_lower:
            venue_type = 'studio'
        elif 'mjc' in name_lower or 'maison des' in name_lower:
            venue_type = 'mjc'
        elif 'espace' in name_lower or 'centre' in name_lower:
            venue_type = 'centre_culturel'
        elif 'bureau' in name_lower:
            venue_type = 'coworking'
        elif 'mairie' in name_lower:
            venue_type = 'mairie'
    
    # Rental inference from URL patterns
    if rental_possible == "unclear" and is_actual:
        if any(kw in url_lower for kw in ['location-salle', 'location_de_salle', 'location-de-salle', 'louer', 'rental']):
            rental_possible = "yes"
    
    return is_actual, venue_type, rental_possible, activity_tags, venue_name_override


def infer_city_from_url(url):
    """Try to extract city hints from URL."""
    url_lower = url.lower()
    city_patterns = {
        'elancourt': 'Élancourt',
        'villejuif': 'Villejuif',
        'malakoff': 'Malakoff',
        'bagneux': 'Bagneux',
        'arcueil': 'Arcueil',
        'bourg-la-reine': 'Bourg-la-Reine',
        'les-molieres': 'Les Mollières',
        'lesmolieres': 'Les Mollières',
        'fontainebleau': 'Fontainebleau',
        'paris': 'Paris',
        'clamart': 'Clamart',
        'montrouge': 'Montrouge',
        'nanterre': 'Nanterre',
    }
    for key, city in city_patterns.items():
        if key in url_lower:
            return city
    return None


for entity in data:
    venue_entity_id = entity['venue_entity_id']
    raw_name = entity['canonical_name']
    canonical_city = entity['canonical_city']
    official_website_url = entity['official_website_url']
    specific_rental_page_url = entity['specific_rental_page_url']
    primary_page_type = entity['primary_page_type']
    
    # Extract content from prompt
    prompt = entity['prompt']
    lines = prompt.split('\n')
    content_start = None
    for j, line in enumerate(lines):
        if 'PAGE CONTENT:' in line:
            content_start = j + 1
            break
    
    if content_start is not None:
        content = '\n'.join(lines[content_start:]).strip()
    else:
        content = ""
    content = content.replace('EXTRACT JSON:', '').strip()
    
    # Check aggregator source
    is_aggregator = "Lien enfant extrait depuis agrégateur" in content
    
    # Classify the entity
    is_actual, venue_type, rental_possible, activity_tags, venue_name_override = classify_entity(entity)
    
    # Override venue name if specified
    venue_name = venue_name_override if venue_name_override else (raw_name if is_actual else None)
    
    # City inference
    inferred_city = infer_city_from_url(official_website_url)
    if not inferred_city and canonical_city:
        inferred_city = canonical_city
    
    # Specific rental page
    specific_rental = None
    if primary_page_type == "official_rental_page":
        specific_rental = official_website_url
    
    # Rental evidence
    rental_evidence = ""
    if rental_possible == "yes":
        url_lower = official_website_url.lower()
        if primary_page_type == "official_rental_page":
            rental_evidence = "Page type is official_rental_page"
        elif 'location' in url_lower or 'salle' in url_lower:
            rental_evidence = f"URL suggests rental: {official_website_url}"
        elif is_aggregator:
            rental_evidence = "Discovered through venue rental aggregator link"
    elif rental_possible == "no":
        rental_evidence = "Course/activity page that does not appear to rent space to third parties"
    
    extraction = {
        "venue_name": {
            "value": venue_name,
            "evidence_quote": raw_name if is_actual else (f"Original name: '{raw_name}' - not a specific rentable venue" if not is_actual else ""),
            "confidence": 0.5 if is_actual else 0.0
        },
        "is_aggregator_listing": {
            "value": is_aggregator,
            "evidence_quote": "Lien enfant extrait depuis agrégateur" if is_aggregator else "",
            "confidence": 0.9 if is_aggregator else 0.3
        },
        "is_multi_venue_listing": {
            "value": False,
            "evidence_quote": "",
            "confidence": 0.3
        },
        "is_actual_venue": {
            "value": is_actual,
            "evidence_quote": "" if is_actual else f"Original name: '{raw_name}' - not a specific rentable venue",
            "confidence": 0.7 if is_actual else 0.8
        },
        "rental_possible": {
            "value": rental_possible,
            "evidence_quote": rental_evidence,
            "confidence": 0.7 if rental_possible == "yes" else (0.6 if rental_possible == "no" else 0.3)
        },
        "address": {
            "value": None,
            "evidence_quote": "",
            "confidence": 0.0
        },
        "city": {
            "value": inferred_city,
            "evidence_quote": f"Inferred from URL: {official_website_url}" if inferred_city else "",
            "confidence": 0.4 if inferred_city else 0.0
        },
        "postal_code": {
            "value": None,
            "evidence_quote": "",
            "confidence": 0.0
        },
        "phone": {
            "value": None,
            "evidence_quote": "",
            "confidence": 0.0
        },
        "email": {
            "value": None,
            "evidence_quote": "",
            "confidence": 0.0
        },
        "website": {
            "value": official_website_url,
            "evidence_quote": "URL from entity metadata",
            "confidence": 0.9
        },
        "specific_rental_page": {
            "value": specific_rental,
            "evidence_quote": "Rental page URL from metadata" if specific_rental else "",
            "confidence": 0.7 if specific_rental else 0.0
        },
        "price": {
            "value": {
                "hourly_eur": None,
                "half_day_eur": None,
                "daily_eur": None,
                "raw": None
            },
            "evidence_quote": "",
            "confidence": 0.0
        },
        "capacity": {
            "value": {
                "seated": None,
                "standing": None,
                "movement": None,
                "surface_m2": None,
                "raw": None
            },
            "evidence_quote": "",
            "confidence": 0.0
        },
        "rental_restrictions": {
            "value": None,
            "evidence_quote": "",
            "confidence": 0.0
        },
        "venue_type": {
            "value": venue_type,
            "evidence_quote": f"Inferred from name/URL: '{raw_name}' at {official_website_url}" if venue_type else "",
            "confidence": 0.5 if venue_type else 0.0
        },
        "activity_tags": {
            "value": activity_tags,
            "evidence_quote": f"Inferred from name: '{raw_name}'" if activity_tags else "",
            "confidence": 0.5 if activity_tags else 0.0
        },
        "pros": {
            "value": [],
            "evidence_quote": "",
            "confidence": 0.0
        },
        "cons": {
            "value": [],
            "evidence_quote": "",
            "confidence": 0.0
        },
        "missing_fields": []
    }
    
    # Build missing_fields list
    missing = []
    if extraction["address"]["value"] is None:
        missing.append("address")
    if extraction["postal_code"]["value"] is None:
        missing.append("postal_code")
    if extraction["phone"]["value"] is None:
        missing.append("phone")
    if extraction["email"]["value"] is None:
        missing.append("email")
    if extraction["price"]["value"]["raw"] is None:
        missing.append("price")
    if extraction["capacity"]["value"]["raw"] is None:
        missing.append("capacity")
    if extraction["rental_restrictions"]["value"] is None:
        missing.append("rental_restrictions")
    if extraction["city"]["value"] is None:
        missing.append("city")
    if extraction["venue_type"]["value"] is None:
        missing.append("venue_type")
    if not activity_tags:
        missing.append("activity_tags")
    if rental_possible == "unclear":
        missing.append("rental_possible")
    if not specific_rental:
        missing.append("specific_rental_page")
    missing.append("pros")
    missing.append("cons")
    
    extraction["missing_fields"] = missing
    
    results.append({
        "venue_entity_id": venue_entity_id,
        "canonical_name": raw_name,
        "extraction": extraction
    })

output_path = 'results_batch_2.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(results)} entities to {output_path}")

# Print summary stats
actual = sum(1 for e in results if e['extraction']['is_actual_venue']['value'])
non_actual = sum(1 for e in results if not e['extraction']['is_actual_venue']['value'])
rental_yes = sum(1 for e in results if e['extraction']['rental_possible']['value'] == 'yes')
rental_no = sum(1 for e in results if e['extraction']['rental_possible']['value'] == 'no')
rental_unclear = sum(1 for e in results if e['extraction']['rental_possible']['value'] == 'unclear')
with_city = sum(1 for e in results if e['extraction']['city']['value'] is not None)
with_type = sum(1 for e in results if e['extraction']['venue_type']['value'] is not None)
with_tags = sum(1 for e in results if e['extraction']['activity_tags']['value'])

print(f'\nSummary:')
print(f'  Total: {len(results)}')
print(f'  Actual venues: {actual}')
print(f'  Non-venue pages: {non_actual}')
print(f'  Rental yes: {rental_yes}')
print(f'  Rental no: {rental_no}')
print(f'  Rental unclear: {rental_unclear}')
print(f'  With city: {with_city}')
print(f'  With venue_type: {with_type}')
print(f'  With activity_tags: {with_tags}')

print(f'\nActual venue entities:')
for e in results:
    if e['extraction']['is_actual_venue']['value']:
        ext = e['extraction']
        print(f'  {e["canonical_name"]}: type={ext["venue_type"]["value"]}, rental={ext["rental_possible"]["value"]}, city={ext["city"]["value"]}, tags={ext["activity_tags"]["value"]}')