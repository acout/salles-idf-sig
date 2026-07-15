#!/usr/bin/env python3
"""
Venue metadata extraction script for batch_0.json.
Extracts structured venue information from page content using
pattern matching and heuristic rules for French venue listings.
"""
import json
import re
import os

BATCH_FILE = "/home/antho/salles-idf-sig/data/discovery_runs/20260620_multisource_lineage_enriched/ai_extraction/batch_0.json"
OUTPUT_FILE = "/home/antho/salles-idf-sig/data/discovery_runs/20260620_multisource_lineage_enriched/ai_extraction/results_batch_0.json"

def load_data():
    with open(BATCH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_page_content(prompt):
    """Extract the page content section from the prompt."""
    marker = "PAGE CONTENT:"
    idx = prompt.find(marker)
    if idx >= 0:
        content = prompt[idx + len(marker):]
        # Remove trailing EXTRACT JSON marker if present
        ej_idx = content.find("\nEXTRACT JSON:")
        if ej_idx >= 0:
            content = content[:ej_idx]
        return content.strip()
    # Fallback: everything after the output format section
    marker2 = "EXTRACT JSON:"
    idx2 = prompt.rfind(marker2)
    if idx2 >= 0:
        # Try to find content between instructions and EXTRACT JSON
        return prompt[:idx2].strip()
    return prompt

def find_evidence(content, patterns, max_len=200):
    """Find evidence quote matching any of the patterns."""
    for pattern in patterns:
        m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if m:
            quote = m.group(0)
            if len(quote) > max_len:
                # Find the sentence containing the match
                start = max(0, m.start() - 50)
                end = min(len(content), m.end() + 50)
                quote = content[start:end].strip()
            return quote[:max_len]
    return ""

def extract_venue_name(entity, content):
    """Extract venue name from content, falling back to canonical name."""
    # Try common patterns for venue name in headings
    patterns = [
        r'<h1[^>]*>(.*?)</h1>',
        r'^#\s+(.+)$',
        r'^(.+?)\s*[|-]\s*(?:Ville|Mairie|Site officiel)',
    ]
    for p in patterns:
        m = re.search(p, content, re.MULTILINE | re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if len(name) > 3 and len(name) < 150:
                return name, m.group(0)[:200], 0.7
    
    # Use canonical_name as fallback
    name = entity['canonical_name']
    # Clean up PDF prefixes etc
    name = re.sub(r'^\[PDF\]\s*', '', name)
    return name, "", 0.5

def determine_listing_type(entity, content):
    """Determine if page is aggregator, multi-venue, or actual venue."""
    url = entity['official_website_url'].lower()
    canonical = entity['canonical_name'].lower()
    page_type = entity.get('primary_page_type', '')
    content_lower = content.lower()
    
    is_aggregator = False
    is_multi_venue = False
    is_actual = True
    agg_quote = ""
    mv_quote = ""
    actual_quote = ""
    
    # Aggregator indicators
    aggregator_domains = ['assoce.fr', 'latribune.fr', 'shootnbox.fr', 'wheree.com', 'yoze.fr', 'kyaoso.com']
    aggregator_keywords = ['liste de', 'annuaire', 'répertoire', 'trouver une salle', 'comparer', 'meilleures salles', 
                          'top des salles', 'sélection de', 'guide des salles', 'annuaire des']
    
    for domain in aggregator_domains:
        if domain in url:
            is_aggregator = True
            agg_quote = f"URL contains aggregator domain: {domain}"
            break
    
    if not is_aggregator:
        for kw in aggregator_keywords:
            if kw in content_lower:
                is_aggregator = True
                agg_quote = find_evidence(content, [re.escape(kw)], 150)
                break
    
    # Multi-venue indicators
    multi_keywords = ['plusieurs salles', 'nos salles', 'nos studios', 'salle 1', 'salle 2', 'studio 1', 'studio 2',
                     'gymnases', 'salles disponibles', 'les salles', 'liste des salles', 'nos espaces',
                     'notre réseau', 'plusieurs espaces', ' différentes salles']
    if entity.get('canonical_city', '') == '':  # No specific city usually means multi-venue or generic
        pass  # Don't set multi-venue just because no city
    
    for kw in multi_keywords:
        if kw in content_lower:
            is_multi_venue = True
            mv_quote = find_evidence(content, [re.escape(kw)], 150)
            break
    
    # Special cases
    if page_type == 'municipal_facility_page':
        # Municipal facility pages often list multiple venues
        if any(kw in content_lower for kw in ['réserver une salle', 'location de salle', 'louer une salle']):
            is_multi_venue = True
            mv_quote = find_evidence(content, ['réserver une salle', 'location de salle', 'louer une salle'], 150)
    
    # Actual venue indicators
    if is_aggregator:
        is_actual = False
        actual_quote = ""
    else:
        rental_kw = ['location', 'louer', 'réserv', 'réservation', 'tarif', 'studio', 'salle de danse', 
                    'à louer', 'location de studio', 'location de salle']
        for kw in rental_kw:
            m = re.search(re.escape(kw), content_lower)
            if m:
                actual_quote = m.group(0)
                break
    
    return is_aggregator, agg_quote, is_multi_venue, mv_quote, is_actual, actual_quote

def determine_rental_possible(entity, content):
    """Determine if venue rental is possible."""
    content_lower = content.lower()
    url = entity['official_website_url'].lower()
    
    # Keywords that indicate rental IS possible
    rental_yes = ['location de', 'à louer', 'louer', 'réserv', 'tarif', 'prix', 'location studio',
                 'location salle', 'réservation en ligne', 'booking', 'disponible à la location',
                 'met à disposition', 'mise à disposition', 'réservation de salle']
    
    # Keywords that indicate it's a course/gym page (NOT rentable)
    course_kw = ['cours de ', 'école de', 'inscription', 'adhésion', 'abonnement', 'cours particulier',
                'cours collectif', 'session de', 'programme', 'coaching', 'entraînement',
                'planning des cours', 'horaires des cours', 'tarif des cours']
    
    # Check if it's a course/gym page
    is_course = False
    for kw in course_kw:
        if kw in content_lower:
            # But also check if they offer rental
            has_rental = any(rkw in content_lower for rkw in rental_yes)
            if not has_rental:
                return "no", find_evidence(content, [re.escape(kw)], 150), 0.7
    
    # Check for rental indicators
    for kw in rental_yes:
        if kw in content_lower:
            return "yes", find_evidence(content, [re.escape(kw)], 150), 0.85
    
    # Check page type
    page_type = entity.get('primary_page_type', '')
    if page_type == 'official_rental_page':
        return "yes", "official_rental_page type", 0.8
    
    # Military/government deliberation PDF
    if 'délibération' in content_lower or 'deliberation' in content_lower:
        return "unclear", find_evidence(content, ['délibération', 'deliberation'], 150), 0.5
    
    return "unclear", "", 0.3

def extract_address(content):
    """Extract address from French content."""
    patterns = [
        r'\d{1,3}[, ]+(?:rue|avenue|bd|boulevard|place|allée|impasse|chemin|route)\s+[^\n,]{3,50}',
        r'(?:rue|avenue|bd|boulevard|place|allée|impasse|chemin|route)\s+[^\n,]{3,50}',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            addr = m.group(0).strip()
            if len(addr) > 8:
                return addr, addr, 0.8
    return None, "", 0.0

def extract_city(content, canonical_city, entity):
    """Extract city from content."""
    if canonical_city:
        # Validate canonical city appears in content
        if canonical_city.lower() in content.lower():
            return canonical_city, canonical_city, 0.9
        else:
            return canonical_city, "", 0.5
    
    # Try to extract from content
    idf_cities = ['paris', 'boulogne-billancourt', 'courbevoie', 'nanterre', 'versailles', 'créteil',
                  'montigny-le-bretonneux', 'montrouge', 'bagneux', 'châtillon', 'issy-les-moulineaux',
                  'vitry-sur-seine', 'ivry-sur-seine', 'saint-denis', 'aubervilliers', 'dunkirk',
                  'meudon', 'clamart', 'sceaux', ' Antony', 'colombes', 'asnières', 'argenteuil',
                  'montreuil', 'saint-mandé', 'vincennes', 'charenton', 'nogent-sur-marne',
                  'joinville-le-pont', 'champs-sur-marne', 'noisy-le-grand', 'Maisons-Alfort',
                  'lagny-sur-marne', 'saint-quentin-en-yvelines', 'chatou', 'le vesinet',
                  'saint-germain-en-laye', 'marly-le-roi', 'chatillon-sur-chalaronne',
                  'viry-chatillon', 'domont', 'chaumontel']
    
    content_lower = content.lower()
    for city in idf_cities:
        if city.lower() in content_lower:
            # Find original case
            m = re.search(re.escape(city), content, re.IGNORECASE)
            if m:
                return city.title(), m.group(0), 0.75
    
    return None, "", 0.0

def extract_postal_code(content):
    """Extract French postal code (5 digits) for Île-de-France."""
    # Île-de-France codes: 75xxx, 77xxx, 78xxx, 91xxx, 92xxx, 93xxx, 94xxx, 95xxx
    patterns = [
        r'\b(75\d{3})\b',
        r'\b(77\d{3})\b', 
        r'\b(78\d{3})\b',
        r'\b(91\d{3})\b',
        r'\b(92\d{3})\b',
        r'\b(93\d{3})\b',
        r'\b(94\d{3})\b',
        r'\b(95\d{3})\b',
    ]
    for p in patterns:
        m = re.search(p, content)
        if m:
            return m.group(1), m.group(1), 0.9
    return None, "", 0.0

def extract_phone(content):
    """Extract French phone number."""
    patterns = [
        r'(?:0[1-9]|\\+33[1-9])[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}',
        r'(?:(?:\\+33|0)[1-9]\s*[\s.-]?\s*\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2})',
        r'(?:01|02|03|04|05|06|07|08|09)[.\s-]?\d{2}[.\s-]?\d{2}[.\s-]?\d{2}[.\s-]?\d{2}',
    ]
    # More flexible pattern
    m = re.search(r'(?:(?:\+33|0)[1-9])[\s.\-]*\d{2}[\s.\-]*\d{2}[\s.\-]*\d{2}[\s.\-]*\d{2}', content)
    if m:
        phone = m.group(0).strip()
        return phone, phone, 0.85
    return None, "", 0.0

def extract_email(content):
    """Extract email address."""
    m = re.search(r'[\w.\-+]+@[\w.\-]+\.\w+', content)
    if m:
        email = m.group(0)
        # Skip generic/common emails
        skip = ['example.com', 'test.com', 'contact@']
        return email, email, 0.85
    return None, "", 0.0

def extract_website(entity, content):
    """Extract website URL."""
    url = entity['official_website_url']
    return url, "", 0.95

def extract_rental_page(entity, content):
    """Extract specific rental page URL if different from main site."""
    rental_url = entity.get('specific_rental_page_url', '')
    if rental_url:
        return rental_url, rental_url, 0.95
    
    # Check content for rental page links
    patterns = [
        r'(?:location|louer|réserv)[^\n]*?(https?://[^\s<"\']+)',
        r'(https?://[^\s<"\']+(?:location|réserv|louer)[^\s<"\']*)',
    ]
    for p in patterns:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            return m.group(1), m.group(0)[:200], 0.7
    
    return None, "", 0.0

def extract_price(content):
    """Extract pricing information in euros."""
    content_lower = content.lower()
    
    # Price per hour
    hourly_patterns = [
        r'(\d+)\s*€\s*/?\s*h(?:eure)?',
        r'(\d+)\s*€\s*par\s*h(?:eure)?',
        r'(\d+)\s*€/h',
        r'tarif[^.]*?(\d+)\s*€[^.]*heure',
    ]
    hourly = None
    for p in hourly_patterns:
        m = re.search(p, content_lower)
        if m:
            hourly = int(m.group(1))
            break
    
    # Price per day
    daily_patterns = [
        r'(\d+)\s*€\s*/?\s*jour',
        r'(\d+)\s*€/j',
        r'tarif[^.]*?(\d+)\s*€[^.]*jour',
    ]
    daily = None
    for p in daily_patterns:
        m = re.search(p, content_lower)
        if m:
            daily = int(m.group(1))
            break
    
    # General price mention
    general_patterns = [
        r'(\d+)\s*€',
        r'prix[^.]{0,30}?(\d+)\s*€',
        r'tarif[^.]{0,30}?(\d+)\s*€',
    ]
    general_price = None
    general_quote = ""
    for p in general_patterns:
        m = re.search(p, content_lower)
        if m:
            general_price = m.group(0)
            general_quote = m.group(0)
            break
    
    price_info = {}
    if hourly is not None:
        price_info['hourly_eur'] = hourly
    if daily is not None:
        price_info['daily_eur'] = daily
    if general_price is not None and not price_info:
        price_info['price_text'] = general_price
    
    if not price_info:
        return None, "", 0.0
    
    quote = general_quote or (f"{hourly}€/h" if hourly else f"{daily}€/jour" if daily else "")
    return price_info, quote, 0.8 if (hourly or daily) else 0.5

def extract_capacity(content):
    """Extract capacity information."""
    content_lower = content.lower()
    
    capacity_info = {}
    
    # Seated capacity
    seated_patterns = [
        r'(\d+)\s*(?:personnes?\s*(?:assis|assises|en\stable)|places?\s*assises?|assis)',
        r'assis[es]*\s*:?\s*(\d+)',
        r'capacité[^.]*?(\d+)\s*personnes?\s*assise',
    ]
    for p in seated_patterns:
        m = re.search(p, content_lower)
        if m:
            capacity_info['seated'] = int(m.group(1))
            break
    
    # Standing capacity
    standing_patterns = [
        r'(\d+)\s*(?:personnes?\s*(?:debout)|places?\s*debout|debout)',
        r'debout\s*:?\s*(\d+)',
    ]
    for p in standing_patterns:
        m = re.search(p, content_lower)
        if m:
            capacity_info['standing'] = int(m.group(1))
            break
    
    # General capacity (number before "personnes" or "places")
    general_patterns = [
        r'(\d+)\s*(?:personnes?|places?|participants?|convives?)',
        r'capacité[^.]{0,20}?(\d+)',
        r'accueill[ie][^.]{0,20}?(\d+)',
        r'jusqu\'?à\s*(\d+)\s*personnes',
    ]
    for p in general_patterns:
        m = re.search(p, content_lower)
        if m and 'capacity' not in capacity_info:
            capacity_info['max'] = int(m.group(1))
            break
    
    # Surface area
    surface_patterns = [
        r'(\d+)\s*m[²²2]',
        r'(\d+)\s*mètres?\s*carrés?',
        r'surface[^.]{0,20}?(\d+)\s*m',
    ]
    for p in surface_patterns:
        m = re.search(p, content_lower)
        if m:
            capacity_info['surface_m2'] = int(m.group(1))
            break
    
    if not capacity_info:
        return None, "", 0.0
    
    return capacity_info, find_evidence(content, [r'(\d+)\s*(?:personnes?|places?|m[²²])'], 100), 0.7

def extract_rental_restrictions(content):
    """Extract rental restrictions or conditions."""
    content_lower = content.lower()
    restrictions = []
    quotes = []
    
    restriction_patterns = [
        (r'chaussure[^.]*interdit', 'Chaussures interdites'),
        (r'talon[^.]*interdit', 'Talons interdits'),
        (r'pas de[^.]{0,30}(?:alcool|boisson|fumée|nourriture)', 'Restrictions alimentaires'),
        (r'occasion[^.]*?(?:mariage|anniversaire|fête)\s*[^.]*?(?:autorisé|accepté|refusé|interdit)', 'Restrictions événements'),
        (r'association[^.]*?(?:uniquement|seulement|obligatoire)', 'Réservé aux associations'),
        (r'surdemande', 'Sur demande'),
        (r'sur\s*devi[sr]', 'Sur devis'),
        (r'association\s+uniquement', 'Associations uniquement'),
        (r'pas\s+d[\'e]\s*(?:musique|son|bruit)\s*après', 'Restriction horaire musique'),
        (r'interdit[^.]{0,40}(?:fumer|animal|chien)', 'Restrictions diverses'),
        (r'conditions?\s*:?\s*[^.]{0,80}', 'Conditions'),
    ]
    
    for pattern, label in restriction_patterns:
        m = re.search(pattern, content_lower)
        if m:
            restrictions.append(label)
            quotes.append(m.group(0)[:150])
    
    if not restrictions:
        return None, "", 0.0
    
    return restrictions, "| ".join(quotes[:2]), 0.6

def extract_venue_type(entity, content):
    """Determine the type of venue."""
    content_lower = content.lower()
    url = entity['official_website_url'].lower()
    canonical = entity['canonical_name'].lower()
    
    venue_types = []
    quotes = []
    
    type_patterns = [
        (r'studio\s+de\s+danse|salle\s+de\s+danse|dance\s+studio', 'studio_de_danse'),
        (r'salle\s+des?\s+fêtes?', 'salle_des_fetes'),
        (r'gymnase|gymnasium', 'gymnase'),
        (r'salle\s+polyvalente|espace\s+polyvalent', 'salle_polyvalente'),
        (r'maison\s+des?\s+associations?', 'maison_des_associations'),
        (r'studio\s+(?:de\s+)?(?:danse|yoga|pilates?|danse)', 'studio'),
        (r'salle\s+de\s+(?:réuni[oe]n|conférence|spectacle)', 'salle_de_reunion'),
        (r'espace\s+(?:culturel|associatif|municipal)', 'espace_culturel'),
        (r'centre\s+(?:sportif|culturel|de\s+danse|aquatique|de\s+congrès)', 'centre'),
        (r'yoga|pilates?', 'studio_yoga'),
        (r'théâtre|theater', 'theatre'),
        (r'école\s+de\s+danse|école\s+de\s+yoga|école\s+de\s+pole', 'ecole'),
        (r'salle\s+municipale', 'salle_municipale'),
    ]
    
    for pattern, vtype in type_patterns:
        if re.search(pattern, content_lower):
            venue_types.append(vtype)
            q = find_evidence(content, [pattern], 80)
            if q:
                quotes.append(q)
    
    # Check URL and canonical name too
    if 'danse' in canonical and 'studio' not in venue_types:
        venue_types.append('studio_de_danse')
    if 'location' in canonical and not venue_types:
        venue_types.append('salle_louable')
    
    if not venue_types:
        if entity.get('primary_page_type') == 'official_rental_page':
            venue_types.append('salle_louable')
        else:
            venue_types.append('unknown')
    
    return venue_types, "| ".join(quotes[:3]), 0.6

def extract_activity_tags(content):
    """Extract activity tags from content."""
    content_lower = content.lower()
    tags = []
    quotes = []
    
    tag_patterns = [
        (r'danse|dance', 'danse'),
        (r'yoga', 'yoga'),
        (r'pilate[ps]?', 'pilates'),
        (r'théâtre|theater|théatre', 'theatre'),
        (r'musique|music', 'musique'),
        (r'sport(?:if|ive)?\b|gymnastique|gym|fitness', 'sport'),
        (r'arts?\s+martiaux|martial', 'arts_martiaux'),
        (r'circ[ua]s?', 'cirque'),
        (r'photo|shooting', 'photo'),
        (r'congrès|conférence|séminaire|colloque', 'evenementiel'),
        (r'mariage|wedding|fête|anniversaire', 'reception'),
        (r'répétition', 'repetition'),
        (r'boxing|boxe|punch|combat', 'boxe'),
        (r'pole\s+dance|pole\s+fit', 'pole_dance'),
        (r'méditat|méditation|relaxation|bien-?être', 'meditation'),
        (r'zumba|aqua|cardio|fitness', 'fitness'),
        (r'tai\s+chi|qi\s+gong', 'arts_energiques'),
        (r'mLoc|MMA|karate|judo|taekwondo', 'arts_martiaux'),
        (r'makers?|fablab|atelier|bricolage', 'atelier'),
        (r'reunion|réuni[oe]n|meeting|collaborat', 'reunion'),
    ]
    
    for pattern, tag in tag_patterns:
        if re.search(pattern, content_lower):
            tags.append(tag)
            q = find_evidence(content, [pattern], 60)
            if q and len(quotes) < 3:
                quotes.append(q)
    
    return list(set(tags)), "| ".join(quotes[:3]), 0.5

def extract_pros_cons(content):
    """Extract pros and cons from content."""
    content_lower = content.lower()
    pros = []
    cons = []
    pros_quotes = []
    cons_quotes = []
    
    # Pros
    pro_patterns = [
        (r'parking', 'Parking disponible'),
        (r'accessible|pmr|handicap', 'Accessible PMR'),
        (r'climatis', 'Climatisé'),
        (r'wi-?fi|internet|fibre', 'WiFi'),
        (r'ventil', 'Ventilé'),
        (r'miroir|mirrors', 'Miroirs'),
        (r'plancher\s+harlequin|plancher\s+professionnel|parquet', 'Plancher professionnel'),
        (r'cuisine|kitchen', 'Cuisine'),
        (r'vendinge|boisson|catering', 'Boissons'),
        (r'neuf|renové|rénové|récent', 'Espace neuf/rénové'),
        (r'éclairage|lumière|luminaire', 'Bon éclairage'),
        (r'240\s*cm|3m\s+x|grande\s+salle|spacieux|spacieuse', 'Espace spacieux'),
        (r'vidéo[- ]?projecteur|projecteur', 'Vidéoprojecteur'),
        (r'sonoris|sonorisation|son', 'Sonorisation'),
    ]
    
    for pattern, pro in pro_patterns:
        if re.search(pattern, content_lower):
            pros.append(pro)
            q = find_evidence(content, [pattern], 80)
            if q and len(pros_quotes) < 3:
                pros_quotes.append(q)
    
    # Cons
    con_patterns = [
        (r'interdict|interdite?|pas\s+de|défend', 'Restrictions d\'usage'),
        (r'chaussure|chassure|talon.*interdit', 'Chaussures/talons interdits'),
        (r'association\s+(?:uniquement|seulement|obligatoire)', 'Réservé associations'),
        (r'occuper|occupé|complet|aucun(?:e)?\s+disponibilité', 'Disponibilité limitée'),
        (r'surdemande|sur\s+devis', 'Prix sur demande'),
        (r'bruit|sonore|musique\s+interdit|pas\s+de\s+musique', 'Restriction sonore'),
    ]
    
    for pattern, con in con_patterns:
        if re.search(pattern, content_lower):
            cons.append(con)
            q = find_evidence(content, [pattern], 80)
            if q and len(cons_quotes) < 3:
                cons_quotes.append(q)
    
    return (pros if pros else None, "| ".join(pros_quotes[:2]), 0.5,
            cons if cons else None, "| ".join(cons_quotes[:2]), 0.5)

def determine_missing_fields(extraction):
    """Determine which fields are missing (null values)."""
    missing = []
    field_checks = {
        'address': extraction.get('address', {}).get('value') is None,
        'city': extraction.get('city', {}).get('value') is None,
        'postal_code': extraction.get('postal_code', {}).get('value') is None,
        'phone': extraction.get('phone', {}).get('value') is None,
        'email': extraction.get('email', {}).get('value') is None,
        'price': extraction.get('price', {}).get('value') is None,
        'capacity': extraction.get('capacity', {}).get('value') is None,
        'rental_restrictions': extraction.get('rental_restrictions', {}).get('value') is None,
    }
    for field, is_missing in field_checks.items():
        if is_missing:
            missing.append(field)
    return missing

def process_entity(entity):
    """Process a single entity and extract all metadata."""
    prompt = entity['prompt']
    content = extract_page_content(prompt)
    
    # Extract all fields
    venue_name_val, venue_name_quote, venue_name_conf = extract_venue_name(entity, content)
    is_agg, agg_quote, is_mv, mv_quote, is_actual, actual_quote = determine_listing_type(entity, content)
    rental_val, rental_quote, rental_conf = determine_rental_possible(entity, content)
    address_val, address_quote, address_conf = extract_address(content)
    city_val, city_quote, city_conf = extract_city(content, entity.get('canonical_city', ''), entity)
    postal_val, postal_quote, postal_conf = extract_postal_code(content)
    phone_val, phone_quote, phone_conf = extract_phone(content)
    email_val, email_quote, email_conf = extract_email(content)
    website_val, website_quote, website_conf = extract_website(entity, content)
    rental_page_val, rental_page_quote, rental_page_conf = extract_rental_page(entity, content)
    price_val, price_quote, price_conf = extract_price(content)
    capacity_val, capacity_quote, capacity_conf = extract_capacity(content)
    restrictions_val, restrictions_quote, restrictions_conf = extract_rental_restrictions(content)
    vtype_val, vtype_quote, vtype_conf = extract_venue_type(entity, content)
    tags_val, tags_quote, tags_conf = extract_activity_tags(content)
    pros_val, pros_quote, pros_conf, cons_val, cons_quote, cons_conf = extract_pros_cons(content)
    
    extraction = {
        "venue_name": {"value": venue_name_val, "evidence_quote": venue_name_quote, "confidence": venue_name_conf},
        "is_aggregator_listing": {"value": is_agg, "evidence_quote": agg_quote, "confidence": 0.8 if is_agg else 0.7},
        "is_multi_venue_listing": {"value": is_mv, "evidence_quote": mv_quote, "confidence": 0.7 if is_mv else 0.5},
        "is_actual_venue": {"value": is_actual, "evidence_quote": actual_quote, "confidence": 0.8 if is_actual else 0.6},
        "rental_possible": {"value": rental_val, "evidence_quote": rental_quote, "confidence": rental_conf},
        "address": {"value": address_val, "evidence_quote": address_quote, "confidence": address_conf},
        "city": {"value": city_val, "evidence_quote": city_quote, "confidence": city_conf},
        "postal_code": {"value": postal_val, "evidence_quote": postal_quote, "confidence": postal_conf},
        "phone": {"value": phone_val, "evidence_quote": phone_quote, "confidence": phone_conf},
        "email": {"value": email_val, "evidence_quote": email_quote, "confidence": email_conf},
        "website": {"value": website_val, "evidence_quote": website_quote, "confidence": website_conf},
        "specific_rental_page": {"value": rental_page_val, "evidence_quote": rental_page_quote, "confidence": rental_page_conf},
        "price": {"value": price_val, "evidence_quote": price_quote, "confidence": price_conf},
        "capacity": {"value": capacity_val, "evidence_quote": capacity_quote, "confidence": capacity_conf},
        "rental_restrictions": {"value": restrictions_val, "evidence_quote": restrictions_quote, "confidence": restrictions_conf},
        "venue_type": {"value": vtype_val, "evidence_quote": vtype_quote, "confidence": vtype_conf},
        "activity_tags": {"value": tags_val, "evidence_quote": tags_quote, "confidence": tags_conf},
        "pros": {"value": pros_val, "evidence_quote": pros_quote, "confidence": pros_conf},
        "cons": {"value": cons_val, "evidence_quote": cons_quote, "confidence": cons_conf},
        "missing_fields": determine_missing_fields({
            "address": {"value": address_val},
            "city": {"value": city_val},
            "postal_code": {"value": postal_val},
            "phone": {"value": phone_val},
            "email": {"value": email_val},
            "price": {"value": price_val},
            "capacity": {"value": capacity_val},
            "rental_restrictions": {"value": restrictions_val},
        }),
    }
    
    return {
        "venue_entity_id": entity['venue_entity_id'],
        "canonical_name": entity['canonical_name'],
        "extraction": extraction
    }

def main():
    data = load_data()
    print(f"Processing {len(data)} entities...")
    
    results = []
    for i, entity in enumerate(data):
        try:
            result = process_entity(entity)
            results.append(result)
            if (i + 1) % 20 == 0:
                print(f"  Processed {i+1}/{len(data)} entities...")
        except Exception as e:
            print(f"  ERROR processing entity {i} ({entity.get('canonical_name', 'unknown')}): {e}")
            # Still include with null extraction
            results.append({
                "venue_entity_id": entity['venue_entity_id'],
                "canonical_name": entity['canonical_name'],
                "extraction": {
                    "venue_name": {"value": entity['canonical_name'], "evidence_quote": "", "confidence": 0.3},
                    "is_aggregator_listing": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "is_multi_venue_listing": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "is_actual_venue": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "rental_possible": {"value": "unclear", "evidence_quote": "", "confidence": 0.0},
                    "address": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "city": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "postal_code": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "phone": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "email": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "website": {"value": entity['official_website_url'], "evidence_quote": "", "confidence": 0.9},
                    "specific_rental_page": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "price": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "capacity": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "rental_restrictions": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "venue_type": {"value": ["unknown"], "evidence_quote": "", "confidence": 0.1},
                    "activity_tags": {"value": [], "evidence_quote": "", "confidence": 0.0},
                    "pros": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "cons": {"value": None, "evidence_quote": "", "confidence": 0.0},
                    "missing_fields": ["address", "city", "postal_code", "phone", "email", "price", "capacity", "rental_restrictions"],
                }
            })
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\nDone! Wrote {len(results)} results to {OUTPUT_FILE}")
    
    # Summary stats
    rental_yes = sum(1 for r in results if r['extraction']['rental_possible']['value'] == 'yes')
    rental_no = sum(1 for r in results if r['extraction']['rental_possible']['value'] == 'no')
    rental_unclear = sum(1 for r in results if r['extraction']['rental_possible']['value'] == 'unclear')
    has_price = sum(1 for r in results if r['extraction']['price']['value'] is not None)
    has_address = sum(1 for r in results if r['extraction']['address']['value'] is not None)
    has_capacity = sum(1 for r in results if r['extraction']['capacity']['value'] is not None)
    is_agg = sum(1 for r in results if r['extraction']['is_aggregator_listing']['value'])
    
    print(f"\nSummary:")
    print(f"  Rental possible: yes={rental_yes}, no={rental_no}, unclear={rental_unclear}")
    print(f"  Has price: {has_price}")
    print(f"  Has address: {has_address}")
    print(f"  Has capacity: {has_capacity}")
    print(f"  Is aggregator: {is_agg}")

if __name__ == "__main__":
    main()