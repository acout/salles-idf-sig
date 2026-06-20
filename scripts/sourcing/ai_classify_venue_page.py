#!/usr/bin/env python3
"""AI-powered venue classifier that reads page content to determine:
1. Is this page about a specific physical venue that can be rented?
2. If yes, what's the dedicated rental/booking page URL?

This replaces the brittle regex/pattern validator with actual AI understanding.
Uses the content already in the content_cache from Tavily discovery.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
RUN_DIR = ROOT / 'data/discovery_runs' / '20260620_multisource_lineage_enriched'

CLASSIFICATION_PROMPT = """Tu es un classificateur de pages web pour des salles louables en Île-de-France.

Analyse le contenu de cette page et détermine :

1. **is_venue_page** : Cette page représente-t-elle UNE salle physique spécifique qu'on peut potentiellement louer pour des cours, répétitions, ateliers, réunions ?
   - OUI si : page d'un studio de yoga, dojo, salle de danse, MJC, centre social, mairie avec salle à louer, etc.
   - NON si : agenda/programmation, PDF de délibération, listing/agrégateur, page "location de salle" générique sans salle identifiée, blog, formulaire de procédure, page contact, page d'événement, page d'association sans salle
   - AMBIGU si : page d'une compagnie qui a probablement une salle mais qui n'en parle pas

2. **venue_name** : Le nom de la salle spécifique (pas le titre de la page web). Vide si pas une salle.

3. **is_rental_page** : Cette page mentionne-t-elle explicitement la location/réservation de salle ? (pas juste "cours" ou "activités")

4. **rental_page_url** : Si la page mentionne une page dédiée à la location (lien "Louer notre salle", "Réservation", etc.), donne l'URL. Sinon vide.

5. **page_category** : La catégorie la plus précise parmi :
   - `venue_with_rental_page` : salle identifiable AVEC page de location dédiée
   - `venue_rental_mentioned` : salle identifiable qui mentionne la location mais sans page dédiée
   - `venue_no_rental_info` : salle identifiable mais aucune info de location
   - `agenda_planning` : agenda, planning, programme
   - `pdf_document` : document PDF (délibération, réglement, etc.)
   - `directory_listing` : annuaire, listing, agrégateur
   - `procedure_form` : procédure, formulaire, démarche
   - `generic_location_page` : page "location de salle" sans salle spécifique
   - `event_page` : page d'événement ponctuel
   - `blog_article` : article de blog
   - `other_non_venue` : autre chose qui n'est pas une salle

Titre de la page : {title}
URL : {url}
Domaine : {domain}
Contenu :
{content}

Réponds UNIQUEMENT en JSON : {{"is_venue_page": true/false, "venue_name": "", "is_rental_page": true/false, "rental_page_url": "", "page_category": ""}}
"""

def classify_entity(entity: dict, content: str | None) -> dict:
    """Classify a single entity using its content."""
    if not content or len(content.strip()) < 50:
        # No content to analyze — use URL heuristics as fallback
        url = entity.get('official_website_url', '') or entity.get('primary_source_url', '')
        url_lower = url.lower()
        name = entity.get('canonical_name', '').lower()
        
        # Basic URL heuristics (less reliable than content but better than nothing)
        non_venue_paths = ['/agenda', '/planning', '/programme', '/evenement', '/events',
                          '/blog', '/article', '/contact', '/a-propos', '/tarifs']
        from urllib.parse import urlparse
        if url:
            path = urlparse(url).path.lower().rstrip('/')
            for nvp in non_venue_paths:
                if path == nvp or path.endswith(nvp):
                    return {'is_venue_page': False, 'venue_name': '', 'is_rental_page': False, 
                            'rental_page_url': '', 'page_category': 'other_non_venue',
                            'rejection_reason': f'URL path {nvp} is not a venue page'}
        
        return {'is_venue_page': None, 'venue_name': '', 'is_rental_page': False,
                'rental_page_url': '', 'page_category': 'unknown_no_content',
                'rejection_reason': 'No content available for AI classification'}
    
    # For now, return the content and let the caller do the AI call
    return {'content_available': True, 'content_length': len(content)}


def load_content_for_entity(entity: dict, observations: list[dict], cache_dir: Path) -> str | None:
    """Load cached content for an entity from its primary observation."""
    obs_ids = entity.get('source_observations', [])
    if not obs_ids:
        return None
    
    # Try each observation's content cache
    for obs_id in obs_ids[:3]:  # Check first 3 observations
        # Content cache naming: obs_{provider}_{hash}.txt
        cache_files = list(cache_dir.glob(f'obs_*_{obs_id.split("_")[-1]}.txt'))
        for cf in cache_files:
            try:
                content = cf.read_text(encoding='utf-8', errors='replace')
                if len(content.strip()) > 50:
                    return content[:3000]  # Cap at 3000 chars for AI context
            except:
                continue
    
    # Also check by URL hash
    primary_url = entity.get('official_website_url', '') or entity.get('primary_source_url', '')
    if primary_url:
        url_hash = hex(abs(hash(primary_url)))[2:][:12]
        cache_files = list(cache_dir.glob(f'url_{url_hash}.txt'))
        for cf in cache_files:
            try:
                content = cf.read_text(encoding='utf-8', errors='replace')
                if len(content.strip()) > 50:
                    return content[:3000]
            except:
                continue
    
    return None


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', default=str(RUN_DIR))
    ap.add_argument('--output', default=str(RUN_DIR / 'ai_venue_classification.json'))
    args = ap.parse_args()
    
    run_dir = Path(args.run_dir)
    output = Path(args.output)
    
    curated = json.loads((run_dir / 'venue_entities_curated.json').read_text(encoding='utf-8'))
    observations = json.loads((run_dir / 'observations_classified.json').read_text(encoding='utf-8'))
    content_dir = run_dir / 'content_cache'
    
    # Build observation lookup
    obs_by_id = {o['observation_id']: o for o in observations}
    
    # Generate prompts for AI classification
    prompts = []
    content_found = 0
    no_content = 0
    
    for entity in curated:
        eid = entity['venue_entity_id']
        content = load_content_for_entity(entity, observations, content_dir)
        
        primary_obs = obs_by_id.get(entity.get('primary_observation_id', ''), {})
        title = primary_obs.get('source_title', '') or entity.get('canonical_name', '')
        url = entity.get('official_website_url', '') or entity.get('primary_source_url', '')
        domain = entity.get('primary_source_domain', '') or (url.split('/')[2] if url else '')
        
        if content and len(content.strip()) > 50:
            content_found += 1
            prompt = CLASSIFICATION_PROMPT.format(
                title=title[:200],
                url=url[:200],
                domain=domain[:100],
                content=content[:2500]
            )
        else:
            no_content += 1
            # Use what we have from Tavily snippets
            snippet = primary_obs.get('description', '') or primary_obs.get('evidence_text', '')
            prompt = CLASSIFICATION_PROMPT.format(
                title=title[:200],
                url=url[:200],
                domain=domain[:100],
                content=f"[Contenu limité] {snippet[:500]}" if snippet else "[Aucun contenu disponible]"
            )
        
        prompts.append({
            'venue_entity_id': eid,
            'canonical_name': entity.get('canonical_name', ''),
            'url': url,
            'has_content': content is not None and len(content.strip()) > 50,
            'prompt': prompt
        })
    
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        'total': len(prompts),
        'with_content': content_found,
        'without_content': no_content,
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'prompts': prompts
    }, ensure_ascii=False, indent=1), encoding='utf-8')
    
    print(f'Generated {len(prompts)} classification prompts')
    print(f'With content: {content_found}')
    print(f'Without content: {no_content}')
    print(f'Saved to {output}')