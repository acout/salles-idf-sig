#!/usr/bin/env python3
"""
Venue metadata extraction script for batch_1.json - v2 (refined).
Processes 127 entities and extracts structured metadata from page content.
"""

import json
import re
import os

BATCH_FILE = "/home/antho/salles-idf-sig/data/discovery_runs/20260620_multisource_lineage_enriched/ai_extraction/batch_1.json"
OUTPUT_FILE = "/home/antho/salles-idf-sig/data/discovery_runs/20260620_multisource_lineage_enriched/ai_extraction/results_batch_1.json"


def extract_page_content(prompt):
    """Extract the page content from the prompt."""
    idx = prompt.find('PAGE CONTENT:')
    if idx < 0:
        return ""
    content = prompt[idx + len('PAGE CONTENT:'):]
    extract_idx = content.find('\n\nEXTRACT JSON:')
    if extract_idx < 0:
        extract_idx = content.find('EXTRACT JSON:')
    if extract_idx >= 0:
        content = content[:extract_idx]
    return content.strip()


def is_aggregator_only(content):
    """Check if content is just an aggregator link with no real venue info."""
    return 'Lien enfant extrait depuis agrégateur' in content


def extract_venue_name(content, canonical_name):
    """Extract venue name - prefer canonical_name when content is noisy."""
    # First, try to find a meaningful name from content lines after removing metadata prefix
    lines = content.split('\n')
    first_line = lines[0].strip() if lines else ""

    # Remove metadata prefix patterns
    prefix_patterns = [
        r'^(?:MJC|mjc|dojo|salle yoga|salle|studio)\s+.*?(?:location\s+salle)\s+\S+\s*—\s*',
        r'^(?:MJC|mjc|dojo|salle yoga|salle|studio)\s+.*?(?:location)\s+\S+\s*—\s*',
    ]

    cleaned = first_line
    for pattern in prefix_patterns:
        m = re.match(pattern, cleaned, re.IGNORECASE)
        if m:
            cleaned = cleaned[m.end():].strip()
            break

    # If after cleaning, the remaining text looks like structured data rather than a name
    # (e.g., "Tarifs ·", "Coordonnées ;", "## ", etc.), fall back to canonical name
    noise_starters = ['Tarifs', 'Coordonnées', '## ', '+ ', '+Carte', 'Lien enfant',
                      'By submitting', 'Salle pouvant', 'Location salle',
                      'Location de salle', 'Location magnifique', 'Découvrez',
                      'Trouver', 'Information légales', 'Les salles sont',
                      'By submitting', 'Unusual venue']

    if any(cleaned.startswith(s) for s in noise_starters):
        return canonical_name, "", 0.4

    # If cleaned name is very long (>200 chars), it's probably not a clean name
    if len(cleaned) > 200:
        return canonical_name, "", 0.4

    # If cleaned name is reasonable (>3 chars and <200), use it
    if len(cleaned) > 3:
        # Truncate at first period or sentence boundary
        for sep in ['. ', ' — ', ' ; ', ' | ']:
            if sep in cleaned:
                shortened = cleaned.split(sep)[0].strip()
                if len(shortened) > 3:
                    return shortened, first_line[:200], 0.6
        return cleaned, first_line[:200], 0.6

    # Fall back to canonical name
    return canonical_name, "", 0.4


def determine_listing_type(content, page_type, url):
    """Determine if this is an aggregator, multi-venue, or actual venue listing."""
    is_aggregator = False
    is_multi_venue = False
    is_actual_venue = True

    if is_aggregator_only(content):
        return True, False, False

    # Aggregator domains
    aggregator_domains = ['kiwiiz.fr/location', 'annuaire-entreprises.data.gouv.fr',
                         'easyzic.com/annuaire']
    for domain in aggregator_domains:
        if domain in url:
            is_aggregator = True
            is_actual_venue = False
            return is_aggregator, is_multi_venue, is_actual_venue

    # Kiwiiz-style aggregated listings
    if re.search(r'\d+\s+salles?\s+à\s+louer\s+entre\s+particuliers', content, re.IGNORECASE):
        is_aggregator = True
        is_actual_venue = False
        return is_aggregator, is_multi_venue, is_actual_venue

    # Multi-venue listing indicators (but NOT aggregator)
    if page_type == 'municipal_facility_page':
        if any(kw in content for kw in ['Nos salles', 'Notre commune dispose', 'salles municipales',
                                          'salles à disposition', 'Location de salles à']):
            is_multi_venue = True

    if any(kw in content for kw in ['Nos studios', 'Nos salles sont', 'salles polyvalents']):
        is_multi_venue = True

    # Specific page type mapping
    if page_type == 'aggregator_listing':
        is_aggregator = True
        is_actual_venue = False

    return is_aggregator, is_multi_venue, is_actual_venue


def extract_rental_possible(content, page_type):
    """Determine if rental is possible."""
    if is_aggregator_only(content):
        return "unclear", "", 0.2

    content_lower = content.lower()

    # Explicit rental indicators
    rental_yes_keywords = ['location de salle', 'location de salles', 'louer', 'louez',
                          'réserv', 'à la location', 'mise à disposition',
                          'mettre à disposition', 'tarif', 'forfait', '€/h',
                          'forfait hebdomadaire', 'book', 'rental', 'available for rent',
                          'salle à la location', 'location salle']
    for kw in rental_yes_keywords:
        if kw in content_lower:
            return "yes", kw, 0.8

    # Price mentions strongly indicate rental
    if re.search(r'\d+\s*€', content):
        return "yes", "price found in euros", 0.7

    # Course/gym indicators (no third-party rental)
    no_rental_keywords = ['cours de yoga', 'cours de danse', 'fitness classes',
                          'association vous propose des cours', 'rendez-vous en ligne',
                          'déborah rouzel']
    for kw in no_rental_keywords:
        if kw in content_lower:
            return "no", kw, 0.6

    # Municipal pages often imply rental is possible
    if page_type == 'municipal_facility_page':
        return "unclear", "", 0.4

    return "unclear", "", 0.3


def extract_address(content):
    """Extract address from content."""
    # Pattern for French addresses with number + street
    patterns = [
        r'(?:(?:Adresse|Address|adresse)\s*[.:]\s*)[\n\s]*(\d+\s+(?:bis\s+)?(?:rue|avenue|av\.?|boulevard|bd|place|pl\.?|allée|all\.?|cours|impasse|chemin|route)\s+[\w\s\'\-]+(?:\s+\d{5})?)',
        r'(\d+\s+(?:bis\s+)?(?:rue|avenue|av\.?|boulevard|bd|place|pl\.?|allée|all\.?|cours|impasse|chemin|route)\s+[\w\s\'\-]+(?:,?\s+\d{5}\s+[A-Za-zÀ-ÿ\-]+)?)',
        r'(\d+\s+(?:bis\s+)?(?:rue|avenue|av\.?|boulevard|bd|place|pl\.?|allée|all\.?|cours|impasse|chemin|route)\s+[\w\s\'\-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            addr = match.group(1).strip()
            # Clean up trailing whitespace/newlines
            addr = re.sub(r'\s+', ' ', addr).strip()
            # Truncate at reasonable end points
            for end_char in ['\n', ';', '·']:
                if end_char in addr:
                    addr = addr.split(end_char)[0].strip()
            if len(addr) > 5 and len(addr) < 200:
                return addr, match.group(0)[:200], 0.7

    return None, "", 0.0


def extract_city_and_postal_code(content, canonical_city):
    """Extract city and postal code."""
    postal_code = None
    city = None
    pc_evidence = ""
    city_evidence = ""

    # French IDF postal codes: 75xxx, 77xxx, 78xxx, 91xxx, 92xxx, 93xxx, 94xxx, 95xxx
    postal_matches = re.findall(r'\b(7[5789]\d{3}|9[1235]\d{3})\b', content)
    if postal_matches:
        postal_code = postal_matches[0]
        pc_evidence = postal_code
        # Try to find city near the postal code
        pc_city_pattern = rf'{postal_code}\s+([A-Za-zÀ-ÿ\s\-\']+?)(?:\s*[,\.\n;]|\s*$)'
        pc_match = re.search(pc_city_pattern, content)
        if pc_match:
            potential_city = pc_match.group(1).strip()
            if len(potential_city) > 2:
                city = potential_city
                city_evidence = pc_match.group(0).strip()

    # If no postal code, try to find IDF cities directly
    if not city:
        city_names = ['Gentilly', 'Villejuif', 'Arcueil', 'Le Kremlin-Bicêtre', 'Kremlin-Bicêtre',
                      'Malakoff', 'Montrouge', 'Clamart', 'Châtillon', 'Chatillon',
                      'Bourg-la-Reine', 'Sceaux', 'Bagneux', 'Fontenay-aux-Roses',
                      'Vanves', 'Cachan', 'Ivry-sur-Seine', 'Vitry-sur-Seine',
                      'Serris', 'Meaux', 'Melun', 'Chelles', 'Paris']
        for cn in city_names:
            if cn in content:
                city = cn
                city_evidence = cn
                break

    # If still no city from content, fall back to canonical
    if not city and canonical_city:
        city = canonical_city
        city_evidence = ""

    city_conf = 0.7 if city and city_evidence else (0.4 if city else 0.0)
    pc_conf = 0.8 if postal_code else 0.0

    return city, city_evidence, city_conf, postal_code, pc_evidence, pc_conf


def extract_phone(content):
    """Extract phone number from content."""
    # Look for labeled phone numbers first
    labeled = re.search(r'(?:Tél|Téléphone|Phone|Portable|Fixe|Tél\.?|tel)\s*(?:fixe|portable)?\s*[.:]?\s*([\d\s\.\-]+)', content, re.IGNORECASE)
    if labeled:
        phone = re.sub(r'[^\d+]', '', labeled.group(1))
        if len(phone) >= 10:
            return phone, labeled.group(0)[:100], 0.8

    # General French phone pattern
    phone_matches = re.findall(r'(?:0[1-9]\s*[\.\-]?\s*)?(\d{2}[\s\.\-]\d{2}[\s\.\-]\d{2}[\s\.\-]\d{2}[\s\.\-]\d{2})', content)
    if phone_matches:
        phone = re.sub(r'[^\d+]', '', phone_matches[0])
        if len(phone) >= 10:
            return phone, phone_matches[0], 0.6

    # Compact French phone numbers
    compact = re.findall(r'(0[1-9]\d{8,9})', content)
    if compact:
        return compact[0], compact[0], 0.7

    return None, "", 0.0


def extract_email(content):
    """Extract email from content."""
    match = re.search(r'[\w\.\-]+@[\w\.\-]+\.\w+', content)
    if match:
        return match.group(0), match.group(0), 0.9
    return None, "", 0.0


def extract_website(content, official_url):
    """Return the official URL as primary website."""
    return official_url, official_url, 0.6


def extract_rental_page(content, specific_rental_url, official_url):
    """Determine if there's a specific rental page."""
    if specific_rental_url:
        return specific_rental_url, "from entity data", 0.9

    # Look for rental-related URLs in content
    rental_keywords = ['location', 'louer', 'réserv', 'booking', 'rent']
    url_matches = re.findall(r'https?://[\w\.\-\/]+', content)
    for url in url_matches:
        for kw in rental_keywords:
            if kw in url.lower() and url != official_url:
                return url, url, 0.6

    return None, "", 0.0


def extract_price(content):
    """Extract price information."""
    prices = {}
    evidence_parts = []

    # Specific named prices in context
    # "Soirée en semaine (18h-0h) : 158 €"
    soir_match = re.search(r'[Ss]oirée en semaine[^:]*?:\s*(\d+)\s*€', content)
    if soir_match:
        prices['evening_weekday_eur'] = int(soir_match.group(1))
        evidence_parts.append(soir_match.group(0)[:100])

    # "Week-end journée : 275 €"
    wkend_match = re.search(r'[Ww]eek[\s-]?end\s*(?:journée)?[^:]*?:\s*(\d+)\s*€', content)
    if wkend_match:
        prices['weekend_daily_eur'] = int(wkend_match.group(1))
        evidence_parts.append(wkend_match.group(0)[:100])

    # Half-day pattern "1/2 journée"
    halfday_match = re.search(r'(\d+)\s*€.*?1/2\s*journée', content)
    if halfday_match:
        prices['half_day_eur'] = int(halfday_match.group(1))
        evidence_parts.append(halfday_match.group(0)[:100])

    # Per-hour price "35€/h" or "35 €/heure"
    hourly_match = re.search(r'(\d+)\s*€\s*/?\s*(?:h|heure)', content, re.IGNORECASE)
    if hourly_match:
        prices['hourly_eur'] = int(hourly_match.group(1))
        evidence_parts.append(hourly_match.group(0))

    # Per-day price "180€/jour"
    daily_match = re.search(r'(\d+)\s*€\s*/?\s*(?:jour|day)', content, re.IGNORECASE)
    if daily_match:
        prices['daily_eur'] = int(daily_match.group(1))
        evidence_parts.append(daily_match.group(0))

    # Rent/apartment prices (for误导 listings like "950 € mensuel", "1.040 €")
    monthly_match = re.search(r'(\d[\d\s.]*)\s*€\s*(?:·|mensuel|/mois|par mois)', content, re.IGNORECASE)
    if monthly_match:
        price_val = monthly_match.group(1).replace('.', '').replace(' ', '')
        prices['monthly_rent_eur'] = int(price_val)
        evidence_parts.append(monthly_match.group(0)[:100])

    # Caution/deposit
    caution_match = re.search(r'caution\s*(?:de\s*)?(\d+)\s*€', content, re.IGNORECASE)
    if caution_match:
        prices['deposit_eur'] = int(caution_match.group(1))
        evidence_parts.append(caution_match.group(0))

    # General prices not yet captured
    if not prices:
        gen_prices = re.findall(r'(\d+)\s*€', content)
        if gen_prices:
            prices['amounts_found_eur'] = [int(p) for p in gen_prices[:5]]
            evidence_parts.append(f"Prices found: {gen_prices[:5]}")

    if prices:
        price_str = json.dumps(prices, ensure_ascii=False)
        evidence_str = " | ".join(evidence_parts[:5])
        conf = 0.7 if any(k in prices for k in ['hourly_eur', 'daily_eur', 'evening_weekday_eur', 'weekend_daily_eur']) else 0.5
        return price_str, evidence_str, conf

    return None, "", 0.0


def extract_capacity(content):
    """Extract capacity information."""
    capacity = {}
    evidence_parts = []

    # "capacité d'accueil de X personnes"
    cap_match = re.search(r'(?:capacité|capacitée?)\s*(?:d\'?\s*accueil\s*)?(?:de\s*)?(\d+)\s*personnes?', content, re.IGNORECASE)
    if cap_match:
        capacity['max'] = int(cap_match.group(1))
        evidence_parts.append(cap_match.group(0)[:100])

    # "peut accueillir jusqu'à X personnes"
    jusqu_match = re.search(r'(?:accueillir|contenir)\s*(?:jusqu\'à\s*)?(\d+)\s*personnes?', content, re.IGNORECASE)
    if jusqu_match:
        capacity['max'] = int(jusqu_match.group(1))
        evidence_parts.append(jusqu_match.group(0)[:100])

    # "X personnes assises/assises"
    seated_match = re.search(r'(\d+)\s*personnes?\s*assises?', content, re.IGNORECASE)
    if seated_match:
        capacity['seated'] = int(seated_match.group(1))
        evidence_parts.append(seated_match.group(0)[:100])

    # "contenir X personnes"
    contenir_match = re.search(r'contenir\s+(\d+)\s*personnes?', content, re.IGNORECASE)
    if contenir_match:
        capacity['max'] = int(contenir_match.group(1))
        evidence_parts.append(contenir_match.group(0)[:100])

    # "Salle pouvant contenir X personnes" (already covered above)
    # "Capacité d'élèves par cours : 25 personnes"
    eleves_match = re.search(r'[Cc]apacité\s+d\'élèves[^:]*:\s*(\d+)', content)
    if eleves_match:
        capacity['movement'] = int(eleves_match.group(1))
        evidence_parts.append(eleves_match.group(0)[:100])

    # General "X personnes"
    if 'max' not in capacity and 'seated' not in capacity and 'movement' not in capacity:
        pers_match = re.search(r'(\d+)\s*personnes?', content)
        if pers_match:
            capacity['max'] = int(pers_match.group(1))
            evidence_parts.append(pers_match.group(0)[:100])

    # Surface area "264 m²" or "264.00 m²" or "200 m²"
    surface_match = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', content)
    if surface_match:
        capacity['surface_m2'] = float(surface_match.group(1))
        evidence_parts.append(surface_match.group(0)[:100])

    # Room dimensions "Salle de réunions : ... 6 personnes"
    room_match = re.search(r'[Ss]alle\s+de\s+réunions?\s*[^:]*:.*?(\d+)\s*personnes?', content, re.IGNORECASE)
    if room_match and 'max' not in capacity and 'seated' not in capacity:
        capacity['seated'] = int(room_match.group(1))
        evidence_parts.append(room_match.group(0)[:100])

    if capacity:
        return json.dumps(capacity, ensure_ascii=False), " | ".join(evidence_parts[:5]), 0.7
    return None, "", 0.0


def extract_rental_restrictions(content):
    """Extract rental restrictions."""
    restrictions = []
    evidence_parts = []

    # Time restrictions
    time_match = re.search(r'(\d+\s*h)\s*(?:au plus tard|au\s+\d+\s*h)', content, re.IGNORECASE)
    if time_match:
        restrictions.append('horaire_limite')
        evidence_parts.append(time_match.group(0)[:100])

    # Reservation via mairie
    if 'mairie' in content.lower() and ('réservation' in content.lower() or 'réserv' in content.lower()):
        restrictions.append('reservation_via_mairie')
        evidence_parts.append("réservation mairie")

    # Caution required
    if re.search(r'caution', content, re.IGNORECASE):
        restrictions.append('caution_requise')
        evidence_parts.append("caution")

    # Insurance required
    if re.search(r'assurance\s+obligatoire', content, re.IGNORECASE):
        restrictions.append('assurance_obligatoire')
        evidence_parts.append("assurance obligatoire")

    # Both private and professional
    if 'particulier' in content.lower() and 'professionnel' in content.lower():
        restrictions.append('particulier_et_professionnel')
        evidence_parts.append("particulier et professionnel")

    # Cancellation policy
    if 'cancellation policy' in content.lower() or 'annulation' in content.lower():
        restrictions.append('politique_annulation')
        evidence_parts.append("politique d'annulation")

    if restrictions:
        return ", ".join(set(restrictions)), " | ".join(evidence_parts[:3]), 0.5
    return None, "", 0.0


def extract_venue_type(content, page_type, canonical_name, url):
    """Determine venue type."""
    content_lower = content.lower()
    name_lower = canonical_name.lower()
    url_lower = url.lower()

    type_indicators = [
        (['dojo', 'arts martiaux', 'judo', 'karaté', 'karate', 'mma', 'boxe', 'aikido'], 'dojo'),
        (['yoga', 'pilates', 'bien-être', 'bien être', 'yoganmove', 'yogmee'], 'yoga_studio'),
        (['studio de danse', 'studios de danse', 'danse', 'dance', 'cours de danse'], 'dance_studio'),
        (['fitness', 'gym', 'sportif'], 'fitness_studio'),
        (['mjc', 'maison des jeunes'], 'mjc'),
        (['maison des associations', 'mcva', 'vie associative'], 'maison_associations'),
        (['salle des fêtes', 'salle polyvalente', 'salle municipale', 'salle andré'], 'salle_polyvalente'),
        (['salle de réunion', 'salle de reunion', 'réunion', 'formation', 'espace formations'], 'salle_reunion'),
        (['salle de sport', 'complexe sportif', 'gymnase', 'sportif'], 'salle_sport'),
        (['école', 'scolaire'], 'school'),
        (['bibliothèque', 'médiathèque'], 'library'),
        (['arena', 'salle d\'exception'], 'events_venue'),
        (['enregistrement', 'studio d\'enregistrement'], 'recording_studio'),
        (['co-working', 'coworking'], 'coworking_space'),
    ]

    for indicators, vtype in type_indicators:
        for indicator in indicators:
            if indicator in content_lower or indicator in name_lower or indicator in url_lower:
                return vtype, indicator, 0.7

    if page_type == 'municipal_facility_page':
        return 'municipal_facility', page_type, 0.4

    return None, "", 0.0


def extract_activity_tags(content):
    """Extract activity tags from content."""
    content_lower = content.lower()
    tags = set()

    activity_map = {
        'yoga': 'yoga', 'pilates': 'pilates', 'danse': 'danse',
        'dance': 'danse', 'arts martiaux': 'arts_martiaux',
        'judo': 'judo', 'karaté': 'karaté', 'karate': 'karaté',
        'boxe': 'boxe', 'mma': 'mma', 'fitness': 'fitness',
        'réunion': 'réunion', 'formation': 'formation',
        'séminaire': 'séminaire', 'concert': 'concert',
        'spectacle': 'spectacle', 'anniversaire': 'anniversaire',
        'fête': 'fête', 'conférence': 'conférence',
        'workshop': 'workshop', 'stage': 'stage',
        'cours': 'cours', 'studio': 'studio',
        'théâtre': 'théâtre', 'méditation': 'méditation',
        'relaxation': 'relaxation', 'bien-être': 'bien-être',
        'mouvement': 'mouvement', 'sport': 'sport',
        'martial': 'arts_martiaux', 'thérapie': 'thérapie',
        'enregistrement': 'studio_enregistrement',
    }

    for keyword, tag in activity_map.items():
        if keyword in content_lower:
            tags.add(tag)

    if tags:
        return sorted(list(tags)), content[:100], 0.5
    return None, "", 0.0


def extract_pros_cons(content):
    """Extract pros and cons from content."""
    pros = []
    cons = []

    pro_checks = [
        (r'miroir', 'miroirs'),
        (r'sono|sonorisation|équipée?\s', 'équipé'),
        (r'climati', 'climatisation'),
        (r'parking|garage', 'parking'),
        (r'cuisine', 'cuisine'),
        (r'vestiaire', 'vestiaires'),
        (r'douche', 'douche'),
        (r'proche\s+(?:métro|bus|transport|Paris)', 'proche_transports'),
        (r'neuf|neuve|rénov', 'neuf/rénové'),
        (r'lumineu', 'lumineux'),
        (r'spacieu', 'spacieux'),
        (r'abordable|prix raisonnable', 'abordable'),
        (r'écran|projecteur|vidéo', 'équipement_audiovisuel'),
    ]

    for pattern, pro in pro_checks:
        if re.search(pattern, content, re.IGNORECASE):
            pros.append(pro)

    con_checks = [
        (r'caution', 'caution_requise'),
        (r'assurance\s+obligatoire', 'assurance_obligatoire'),
        (r'au\s+plus\s+tard', 'horaire_limite'),
    ]

    for pattern, con in con_checks:
        if re.search(pattern, content, re.IGNORECASE):
            cons.append(con)

    return pros if pros else None, cons if cons else None


def determine_missing_fields(extraction):
    """Determine which fields are missing or have low confidence."""
    missing = []
    field_names = ['address', 'postal_code', 'phone', 'email', 'price',
                   'capacity', 'venue_type', 'specific_rental_page']
    for field in field_names:
        data = extraction.get(field, {})
        if data.get('value') is None or data.get('confidence', 0) < 0.3:
            missing.append(field)
    return missing


def process_entity(entity):
    """Process a single entity and extract all metadata fields."""
    prompt = entity['prompt']
    content = extract_page_content(prompt)

    canonical_name = entity.get('canonical_name', '')
    canonical_city = entity.get('canonical_city', '')
    official_url = entity.get('official_website_url', '')
    specific_rental_url = entity.get('specific_rental_page_url', '')
    page_type = entity.get('primary_page_type', '')

    # Handle aggregator-only content (just a link)
    if is_aggregator_only(content):
        link_match = re.search(r'(https?://\S+)', content)
        extraction = {
            'venue_name': {'value': canonical_name, 'evidence_quote': '', 'confidence': 0.2},
            'is_aggregator_listing': {'value': True, 'evidence_quote': 'Lien enfant extrait depuis agrégateur', 'confidence': 0.9},
            'is_multi_venue_listing': {'value': False, 'evidence_quote': '', 'confidence': 0.5},
            'is_actual_venue': {'value': False, 'evidence_quote': 'Lien enfant extrait depuis agrégateur', 'confidence': 0.8},
            'rental_possible': {'value': 'unclear', 'evidence_quote': '', 'confidence': 0.2},
            'address': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'city': {'value': canonical_city if canonical_city else None, 'evidence_quote': '', 'confidence': 0.3 if canonical_city else 0.0},
            'postal_code': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'phone': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'email': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'website': {'value': link_match.group(1) if link_match else official_url, 'evidence_quote': link_match.group(0) if link_match else official_url, 'confidence': 0.5 if link_match else 0.2},
            'specific_rental_page': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'price': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'capacity': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'rental_restrictions': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'venue_type': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'activity_tags': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'pros': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
            'cons': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
        }
        extraction['missing_fields'] = {
            'value': ['address', 'postal_code', 'phone', 'email', 'price', 'capacity', 'venue_type', 'specific_rental_page'],
            'evidence_quote': '', 'confidence': 0.9
        }
        return extraction

    # Full extraction
    is_aggregator, is_multi_venue, is_actual_venue = determine_listing_type(content, page_type, official_url)
    venue_name, vn_evidence, vn_conf = extract_venue_name(content, canonical_name)
    rental_possible, rp_evidence, rp_conf = extract_rental_possible(content, page_type)
    address, addr_evidence, addr_conf = extract_address(content)
    city, city_evidence, city_conf, postal_code, pc_evidence, pc_conf = extract_city_and_postal_code(content, canonical_city)
    phone, phone_evidence, phone_conf = extract_phone(content)
    email, email_evidence, email_conf = extract_email(content)
    website, web_evidence, web_conf = extract_website(content, official_url)
    rental_page, rp_page_evidence, rp_page_conf = extract_rental_page(content, specific_rental_url, official_url)
    price, price_evidence, price_conf = extract_price(content)
    capacity, cap_evidence, cap_conf = extract_capacity(content)
    restrictions, rest_evidence, rest_conf = extract_rental_restrictions(content)
    venue_type, vt_evidence, vt_conf = extract_venue_type(content, page_type, canonical_name, official_url)
    activity_tags, at_evidence, at_conf = extract_activity_tags(content)
    pros, cons = extract_pros_cons(content)

    extraction = {
        'venue_name': {'value': venue_name, 'evidence_quote': vn_evidence, 'confidence': vn_conf},
        'is_aggregator_listing': {'value': is_aggregator, 'evidence_quote': 'aggregator listing' if is_aggregator else ('multi-venue listing' if is_multi_venue else 'single venue page'), 'confidence': 0.8},
        'is_multi_venue_listing': {'value': is_multi_venue, 'evidence_quote': 'multiple venues listed' if is_multi_venue else '', 'confidence': 0.7},
        'is_actual_venue': {'value': is_actual_venue, 'evidence_quote': '', 'confidence': 0.7},
        'rental_possible': {'value': rental_possible, 'evidence_quote': rp_evidence[:200] if rp_evidence else '', 'confidence': rp_conf},
        'address': {'value': address, 'evidence_quote': addr_evidence[:200] if addr_evidence else '', 'confidence': addr_conf},
        'city': {'value': city, 'evidence_quote': city_evidence, 'confidence': city_conf},
        'postal_code': {'value': postal_code, 'evidence_quote': pc_evidence, 'confidence': pc_conf},
        'phone': {'value': phone, 'evidence_quote': phone_evidence[:100] if phone_evidence else '', 'confidence': phone_conf},
        'email': {'value': email, 'evidence_quote': email_evidence, 'confidence': email_conf},
        'website': {'value': website, 'evidence_quote': web_evidence, 'confidence': web_conf},
        'specific_rental_page': {'value': rental_page, 'evidence_quote': rp_page_evidence[:200] if rp_page_evidence else '', 'confidence': rp_page_conf},
        'price': {'value': price, 'evidence_quote': price_evidence[:200] if price_evidence else '', 'confidence': price_conf if price else 0.0},
        'capacity': {'value': capacity, 'evidence_quote': cap_evidence[:200] if cap_evidence else '', 'confidence': cap_conf if capacity else 0.0},
        'rental_restrictions': {'value': restrictions, 'evidence_quote': rest_evidence[:200] if rest_evidence else '', 'confidence': rest_conf if restrictions else 0.0},
        'venue_type': {'value': venue_type, 'evidence_quote': vt_evidence, 'confidence': vt_conf},
        'activity_tags': {'value': activity_tags, 'evidence_quote': at_evidence[:200] if at_evidence else '', 'confidence': at_conf if activity_tags else 0.0},
        'pros': {'value': pros, 'evidence_quote': ', '.join(pros) if pros else '', 'confidence': 0.5 if pros else 0.0},
        'cons': {'value': cons, 'evidence_quote': ', '.join(cons) if cons else '', 'confidence': 0.5 if cons else 0.0},
    }

    extraction['missing_fields'] = {
        'value': determine_missing_fields(extraction),
        'evidence_quote': '',
        'confidence': 0.9
    }

    return extraction


def main():
    with open(BATCH_FILE, 'r') as f:
        data = json.load(f)

    print(f"Processing {len(data)} entities...")

    results = []
    for i, entity in enumerate(data):
        try:
            extraction = process_entity(entity)
            result = {
                'venue_entity_id': entity['venue_entity_id'],
                'canonical_name': entity['canonical_name'],
                'extraction': extraction
            }
            results.append(result)
            if (i + 1) % 25 == 0:
                print(f"  Processed {i + 1}/{len(data)}")
        except Exception as e:
            print(f"  ERROR processing entity {i}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'venue_entity_id': entity.get('venue_entity_id', f'unknown_{i}'),
                'canonical_name': entity.get('canonical_name', ''),
                'extraction': {
                    'venue_name': {'value': entity.get('canonical_name', ''), 'evidence_quote': '', 'confidence': 0.1},
                    'is_aggregator_listing': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'is_multi_venue_listing': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'is_actual_venue': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'rental_possible': {'value': 'unclear', 'evidence_quote': '', 'confidence': 0.0},
                    'address': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'city': {'value': entity.get('canonical_city', None), 'evidence_quote': '', 'confidence': 0.1},
                    'postal_code': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'phone': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'email': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'website': {'value': entity.get('official_website_url', None), 'evidence_quote': '', 'confidence': 0.1},
                    'specific_rental_page': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'price': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'capacity': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'rental_restrictions': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'venue_type': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'activity_tags': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'pros': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'cons': {'value': None, 'evidence_quote': '', 'confidence': 0.0},
                    'missing_fields': {'value': ['all'], 'evidence_quote': '', 'confidence': 0.9},
                }
            })

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Wrote {len(results)} entities to {OUTPUT_FILE}")

    # Print summary stats
    rental_yes = sum(1 for r in results if r['extraction']['rental_possible']['value'] == 'yes')
    rental_no = sum(1 for r in results if r['extraction']['rental_possible']['value'] == 'no')
    rental_unclear = sum(1 for r in results if r['extraction']['rental_possible']['value'] == 'unclear')
    is_agg = sum(1 for r in results if r['extraction']['is_aggregator_listing']['value'] == True)
    is_multi = sum(1 for r in results if r['extraction']['is_multi_venue_listing']['value'] == True)
    is_actual = sum(1 for r in results if r['extraction']['is_actual_venue']['value'] == True)
    has_price = sum(1 for r in results if r['extraction']['price']['value'] is not None)
    has_capacity = sum(1 for r in results if r['extraction']['capacity']['value'] is not None)
    has_address = sum(1 for r in results if r['extraction']['address']['value'] is not None)
    has_phone = sum(1 for r in results if r['extraction']['phone']['value'] is not None)
    has_email = sum(1 for r in results if r['extraction']['email']['value'] is not None)
    has_type = sum(1 for r in results if r['extraction']['venue_type']['value'] is not None)

    print(f"\nSummary:")
    print(f"  Total: {len(results)}")
    print(f"  Rental: yes={rental_yes}, no={rental_no}, unclear={rental_unclear}")
    print(f"  Listing type: aggregator={is_agg}, multi-venue={is_multi}, actual_venue={is_actual}")
    print(f"  With price: {has_price}")
    print(f"  With capacity: {has_capacity}")
    print(f"  With address: {has_address}")
    print(f"  With phone: {has_phone}")
    print(f"  With email: {has_email}")
    print(f"  With venue_type: {has_type}")


if __name__ == '__main__':
    main()