#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from common import ROOT, norm_text, now_iso

POSITIVE_PATTERNS = [
    (r'location\s+de\s+salle', 'location de salle'),
    (r'location\s+de\s+salles', 'location de salles'),
    (r'salle[s]?\s+à\s+louer', 'salle à louer'),
    (r'louer\s+(?:une|la|nos|notre)?\s*salle', 'louer une salle'),
    (r'louer\s+(?:un|le|nos|notre)?\s*studio', 'louer un studio'),
    (r'location\s+studio', 'location studio'),
    (r'privatisation', 'privatisation'),
    (r'privatiser', 'privatiser'),
    (r'mise\s+à\s+disposition', 'mise à disposition'),
    (r'réservation\s+de\s+salle', 'réservation de salle'),
    (r'reserver\s+(?:une|la)?\s*salle', 'réserver salle'),
    (r'réserver\s+(?:une|la)?\s*salle', 'réserver salle'),
    (r'tarif[s]?\s+de\s+location', 'tarifs de location'),
    (r'demande\s+de\s+location', 'demande de location'),
    (r'accueil(?:lir)?\s+(?:vos|des)?\s*(?:évènements|evenements|stages|ateliers|séminaires)', 'accueil stages/ateliers/événements'),
    (r'espaces?\s+(?:à\s+)?(?:louer|privatiser|réserver)', 'espace à louer/privatiser'),
]

NEGATIVE_PATTERNS = [
    (r'fitness\s*park', 'Fitness Park'),
    (r'salle\s+de\s+sport', 'salle de sport'),
    (r'club\s+de\s+sport', 'club de sport'),
    (r'abonnement[s]?', 'abonnement'),
    (r'adhérent[s]?\s+uniquement', 'adhérents uniquement'),
    (r'cours\s+collectifs?', 'cours collectifs'),
    (r'planning\s+des\s+cours', 'planning des cours'),
    (r'cours\s+de\s+yoga', 'cours de yoga'),
    (r'cours\s+de\s+danse', 'cours de danse'),
    (r'inscription\s+aux\s+cours', 'inscription aux cours'),
    (r'coach(?:ing)?\s+personnel', 'coaching personnel'),
    (r'acheter\s+un\s+pass', 'achat pass'),
    (r'réserver\s+un\s+cours', 'réserver un cours'),
]

# Domains or names that very often represent classes/gyms rather than rentable rooms.
LIKELY_UNRENTABLE_HINTS = [
    'fitnesspark', 'basic-fit', 'neoness', 'keepcool', 'cercles de la forme', 'club med gym',
]


def collect_matches(patterns: list[tuple[str, str]], text: str) -> list[str]:
    out = []
    for pattern, label in patterns:
        if re.search(pattern, text, flags=re.I):
            out.append(label)
    return sorted(set(out))


def classify_record(record: dict) -> dict:
    r = dict(record)
    text = ' '.join(str(r.get(k, '')) for k in (
        'name', 'category', 'description', 'evidence_text', 'formal_evidence_text', 'formal_page_title',
        'source_url', 'website', 'price_text', 'capacity_text', 'email_questions'
    ))
    nt = norm_text(text)
    positives = collect_matches(POSITIVE_PATTERNS, text)
    negatives = collect_matches(NEGATIVE_PATTERNS, text)
    domainish = norm_text(str(r.get('source_url') or '') + ' ' + str(r.get('website') or '') + ' ' + str(r.get('name') or ''))
    if any(h in domainish for h in LIKELY_UNRENTABLE_HINTS):
        negatives.append('enseigne fitness probablement non louable')
    negatives = sorted(set(negatives))

    # Conservative rule: explicit rental wins over generic course/gym language, because a yoga/dance studio may both run classes and rent rooms.
    if positives:
        status = 'possible'
        confidence = 'high' if len(positives) >= 2 or any(p in positives for p in ('location de salle', 'location de salles', 'salle à louer', 'privatisation')) else 'medium'
    elif negatives:
        status = 'unlikely'
        confidence = 'high' if any(x in negatives for x in ('Fitness Park', 'enseigne fitness probablement non louable', 'abonnement')) else 'medium'
    else:
        status = 'unclear'
        confidence = 'low'

    # Aggregators advertise rental generally, but a listing page may still not prove this exact room is directly rentable.
    if str(r.get('is_aggregator') or '').lower() == 'yes' and status == 'possible':
        confidence = 'medium'

    r['rental_possible_status'] = status
    r['rental_possible_confidence'] = confidence
    r['rental_positive_signals'] = '; '.join(positives)
    r['rental_negative_signals'] = '; '.join(negatives)
    if status == 'possible':
        q = 'Confirmer modalités exactes de location, disponibilités, prix, capacité et conditions.'
    elif status == 'unlikely':
        q = 'Vérifier s’ils louent réellement une salle à des tiers ; le site ressemble à des cours/abonnements plutôt qu’à une location.'
    else:
        q = 'Demander explicitement si une location/privatisation de salle est possible.'
    r['rental_email_question'] = q

    missing = str(r.get('missing_formal_fields') or '').strip()
    existing_q = str(r.get('email_questions') or '').strip()
    if q and q not in existing_q:
        r['email_questions'] = (existing_q + '; ' + q).strip('; ') if existing_q else q
    if status != 'possible':
        # Make this visible as a missing decision, without pretending a formal field is absent.
        r['rental_decision_needed'] = 'yes'
    else:
        r['rental_decision_needed'] = 'no'
    return r


def main():
    ap = argparse.ArgumentParser(description='Classify whether each sourced item appears to offer room rental/privatization.')
    ap.add_argument('input')
    ap.add_argument('--output', required=True)
    ap.add_argument('--report', default='')
    args = ap.parse_args()

    records = json.loads(Path(args.input).read_text(encoding='utf-8'))
    out = [classify_record(r) for r in records]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {
        'generated_at': now_iso(),
        'input_records': len(records),
        'output_records': len(out),
        'rental_possible_status': dict(Counter(r.get('rental_possible_status') for r in out)),
        'rental_possible_confidence': dict(Counter(r.get('rental_possible_confidence') for r in out)),
        'top_positive_signals': dict(Counter(sig for r in out for sig in str(r.get('rental_positive_signals') or '').split('; ') if sig).most_common(25)),
        'top_negative_signals': dict(Counter(sig for r in out for sig in str(r.get('rental_negative_signals') or '').split('; ') if sig).most_common(25)),
        'output': str(output),
    }
    report_path = Path(args.report) if args.report else output.with_suffix('.report.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
