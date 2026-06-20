#!/usr/bin/env python3
"""Systematic IDF commune-by-commune sourcing pipeline.

This script generates Tavily search prompts for every IDF commune, prioritizing
the ones we haven't covered yet. It outputs a JSON file that can be fed into
the discovery pipeline.

Strategy per commune:
1. Generate FR search prompts targeting small rental venues
2. Deduplicate against already-covered communes
3. Output prompt config ready for discover_with_tavily.py

Usage:
    # Show coverage gaps and generate prompts for missing communes
    env -u HTTP_PROXY -u HTTPS_PROXY python3 scripts/sourcing/source_systematic_idf.py

    # Only south banlieue priority (94 + 92 southern)
    python3 scripts/sourcing/source_systematic_idf.py --priority south

    # Specific departments only
    python3 scripts/sourcing/source_systematic_idf.py --dept 94 92
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# ── IDF Commune Reference ──────────────────────────────────────────────────
# Complete official commune list by department
IDF_COMMUNES: dict[str, list[str]] = {
    "75": ["Paris"],
    "92": [
        "Antony", "Asnières-sur-Seine", "Bagneux", "Bois-Colombes", "Boulogne-Billancourt",
        "Bougival", "Bourg-la-Reine", "Châtenay-Malabry", "Châtillon", "Clamart",
        "Clichy", "Colombes", "Courbevoie", "Fontenay-aux-Roses", "Garches",
        "La Garenne-Colombes", "Gennevilliers", "Issy-les-Moulineaux", "Levallois-Perret",
        "Malakoff", "Meudon", "Montrouge", "Nanterre", "Neuilly-sur-Seine",
        "Le Plessis-Robinson", "Puteaux", "Rueil-Malmaison", "Saint-Cloud",
        "Sceaux", "Sèvres", "Suresnes", "Vanves", "Vaucresson", "Ville-d'Avray",
        "Villeneuve-la-Garenne",
    ],
    "93": [
        "Aubervilliers", "Aulnay-sous-Bois", "Bagnolet", "Le Blanc-Mesnil", "Bobigny",
        "Bondy", "Le Bourget", "Clichy-sous-Bois", "Coubron", "Drancy",
        "Dugny", "Épinay-sur-Seine", "Gagny", "Les Lilas", "Livry-Gargan",
        "Montfermeil", "Montreuil", "Neuilly-sur-Marne", "Noisy-le-Grand",
        "Noisy-le-Sec", "Pantin", "Les Pavillons-sous-Bois", "Pierrefitte-sur-Seine",
        "Le Pré-Saint-Gervais", "Le Raincy", "Romainville", "Rosny-sous-Bois",
        "Saint-Denis", "Saint-Mandé", "Saint-Ouen-sur-Seine", "Sevran",
        "Stains", "Tremblay-en-France", "Vaujours", "Villemomble", "Villepinte",
        "Villetaneuse",
    ],
    "94": [
        "Alfortville", "Arcueil", "Boissy-Saint-Léger", "Bonneuil-sur-Marne", "Bry-sur-Marne",
        "Cachan", "Champigny-sur-Marne", "Charenton-le-Pont", "Chevilly-Larue",
        "Choisy-le-Roi", "Créteil", "Fontenay-sous-Bois", "Fresnes", "Gentilly",
        "L'Haÿ-les-Roses", "Ivry-sur-Seine", "Joinville-le-Pont", "Le Kremlin-Bicêtre",
        "Limeil-Brévannes", "Maisons-Alfort", "Marolles-en-Brie", "Nogent-sur-Marne",
        "Orly", "Ormesson-sur-Marne", "Périgny", "Le Perreux-sur-Marne",
        "Le Plessis-Trévise", "La Queue-en-Brie", "Rungis", "Saint-Mandé",
        "Saint-Maur-des-Fossés", "Saint-Maur-Créteil", "Santeny", "Sucy-en-Brie",
        "Thiais", "Valenton", "Villecresnes", "Villeneuve-Saint-Georges",
        "Villiers-sur-Marne", "Vincennes", "Vitry-sur-Seine",
    ],
    "91": [
        "Arpajon", "Athis-Mons", "Ballancourt-sur-Essonne", "Boigneville",
        "Boussy-Saint-Antoine", "Brétigny-sur-Orge", "Briis-sous-Forges", "Brunoy",
        "Bures-sur-Yvette", "Chilly-Mazarin", "Corbeil-Essonne", "Courcouronnes",
        "Dourdan", "Draveil", "Épinay-sous-Sénart", "Étampes", "Évry-Courcouronnes",
        "Fleury-Mérogis", "Gif-sur-Yvette", "Grigny", "Igny", "Juvisy-sur-Orge",
        "Linas", "Longjumeau", "Mennecy", "Massy", "Morsang-sur-Orge",
        "Orsay", "Palaiseau", "Paray-Vieille-Poste", "Ris-Orangis", "Saclay",
        "Sainte-Geneviève-des-Bois", "Saint-Michel-sur-Orge", "Savigny-sur-Orge",
        "Les Ulis", "Viry-Châtillon", "Wissous", "Yerres",
    ],
    "77": [
        "Brie-Comte-Robert", "Bussy-Saint-Georges", "Champs-sur-Marne", "Chelles",
        "Combs-la-Ville", "Dammarie-les-Lys", "Fontainebleau", "La Ferté-sous-Jouarre",
        "Lésigny", "Lieusaint", "Lognes", "Meaux", "Melun", "Mitry-Mory",
        "Moissy-Cramayel", "Montereau-Fault-Yonne", "Nandy", "Noisiel",
        "Ozoir-la-Ferrière", "Pontault-Combault", "Provins", "Roissy-en-Brie",
        "Savigny-le-Temple", "Serris", "Torcy", "Vaires-sur-Marne",
        "Villeparisis",
    ],
    "78": [
        "Achères", "Andrésy", "Bonnières-sur-Seine", "Bougival", "Buc",
        "Carrières-sur-Seine", "Carrières-sous-Poissy", "Chanteloup-les-Vignes",
        "Chatou", "Conflans-Sainte-Honorine", "Élancourt", "Les Essarts-le-Roi",
        "Gargenville", "Guyancourt", "Houilles", "Jouy-en-Josas",
        "La Celle-Saint-Cloud", "Le Chesnay-Rocquencourt", "Les Mureaux", "Limay",
        "Maisons-Laffitte", "Marly-le-Roi", "Mantes-la-Jolie", "Maurepas",
        "Mesnil-Saint-Denis", "Montigny-le-Bretonneux", "Le Pecq", "Plaisir",
        "Poissy", "Le Port-Marly", "Rambouillet", "Saint-Cyr-l'École",
        "Saint-Germain-en-Laye", "Sartrouville", "Trappes", "Triel-sur-Seine",
        "Le Vésinet", "Versailles", "Viroflay", "Voisins-le-Bretonneux",
    ],
    "95": [
        "Argenteuil", "Arnouville", "Auvers-sur-Oise", "Beauchamp", "Bezons",
        "Cergy", "Cormeilles-en-Parisis", "Deuil-la-Barre", "Éaubonne",
        "Enghien-les-Bains", "Éragny", "Ermont", "Franconville",
        "Garges-lès-Gonesse", "Gonesse", "Herblay-sur-Seine", "L'Isle-Adam",
        "La Frette-sur-Seine", "Margency", "Menucourt", "Mériel",
        "Méry-sur-Oise", "Montigny", "Montmorency", "Osny", "Persan",
        "Pontoise", "Saint-Gratien", "Saint-Leu-la-Forêt",
        "Saint-Ouen-l'Aumône", "Sannois", "Sarcelles",
        "Soisy-sous-Montmorency", "Taverny", "Valmondois", "Vauréal",
        "Villiers-le-Bel",
    ],
}

# Priority communes = Anthony's neighbourhood + south banlieue
PRIORITY_SOUTH: dict[str, list[str]] = {
    "92": [
        "Châtillon", "Montrouge", "Bagneux", "Malakoff", "Clamart",
        "Fontenay-aux-Roses", "Vanves", "Issy-les-Moulineaux",
        "Meudon", "Bougival", "Le Plessis-Robinson", "Sceaux",
        "Antony", "Châtenay-Malabry", "Bourg-la-Reine",
    ],
    "94": [
        "Cachan", "Arcueil", "Gentilly", "Villejuif",
        "Le Kremlin-Bicêtre", "Ivry-sur-Seine", "Vitry-sur-Seine",
        "Fresnes", "L'Haÿ-les-Roses", "Chevilly-Larue", "Rungis",
        "Choisy-le-Roi", "Thiais", "Orly", "Saint-Mandé",
        "Vincennes", "Charenton-le-Pont", "Joinville-le-Pont",
    ],
}


def normalize_city(city: str) -> str:
    """Normalize city name for comparison."""
    import re
    c = city.lower().strip()
    c = c.replace("-", " ").replace("â", "a").replace("é", "e").replace("è", "e")
    c = c.replace("ê", "e").replace("î", "i").replace("ô", "o").replace("ù", "u")
    c = c.replace("ç", "c").replace("'", " ").replace("  ", " ")
    # Remove articles
    for prefix in ["la ", "le ", "les ", "l "]:
        if c.startswith(prefix):
            c = c[len(prefix):]
    return c.strip()


def compute_coverage(import_queue_path: Path, salles_all_path: Path) -> dict[str, set[str]]:
    """Compute which communes are already covered."""
    covered: dict[str, set[str]] = {}
    for p in [import_queue_path, salles_all_path]:
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for f in data.get("features", []):
            props = f.get("properties", {})
            city = props.get("city", "") or props.get("commune", "")
            dept = props.get("department", "")
            if city and dept:
                covered.setdefault(dept, set()).add(normalize_city(city))
    return covered


def generate_prompts_for_commune(commune: str, dept: str) -> list[dict[str, str]]:
    """Generate Tavily search prompts for a specific commune."""
    prompts = [
        {
            "id": f"fr_{normalize_city(commune)}_officiel",
            "query": f"Louer petite salle {commune} {dept} site officiel mairie association",
            "prompt": (
                f"Pages officielles pour louer une petite salle à {commune} ({dept}). "
                f"Salle 10-30 personnes, atelier, yoga, danse, dojo. "
                f"Exclure hôtels, mariage, coworking, annuaires."
            ),
        },
        {
            "id": f"fr_{normalize_city(commune)}_prive",
            "query": f"Salle à louer {commune} atelier yoga danse particulier",
            "prompt": (
                f"Salles privées à louer à {commune} ({dept}). "
                f"Studio yoga, salle danse, atelier artistique, dojo. "
                f"Exclure Airbnb, Peerspace, mariage, séminaire entreprise."
            ),
        },
    ]
    return prompts


def main() -> None:
    ap = argparse.ArgumentParser(description="Systematic IDF commune sourcing")
    ap.add_argument("--priority", choices=["south", "all"], default="south",
                    help="Priority: 'south' for Cachan/Châtillon area, 'all' for entire IDF")
    ap.add_argument("--dept", nargs="+", help="Restrict to specific department codes")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of communes to process")
    ap.add_argument("--output", default="data/discovery_runs/systematic_idf_prompts.json")
    args = ap.parse_args()

    import_queue_path = ROOT / "public" / "import_queue.geojson"
    salles_all_path = ROOT / "public" / "salles_all_idf.geojson"
    covered = compute_coverage(import_queue_path, salles_all_path)

    # Select communes to process
    if args.priority == "south":
        target_communes = PRIORITY_SOUTH
    else:
        target_communes = IDF_COMMUNES

    if args.dept:
        target_communes = {d: v for d, v in target_communes.items() if d in args.dept}

    # Find missing communes
    missing: list[dict[str, Any]] = []
    covered_count: dict[str, int] = {}
    for dept, communes in target_communes.items():
        dept_covered = covered.get(dept, set())
        covered_count[dept] = 0
        for commune in communes:
            norm = normalize_city(commune)
            if norm in dept_covered:
                covered_count[dept] += 1
                continue
            missing.append({"commune": commune, "dept": dept, "norm": norm})

    if args.limit > 0:
        missing = missing[:args.limit]

    # Generate prompts
    all_prompts: list[dict[str, Any]] = []
    for entry in missing:
        prompts = generate_prompts_for_commune(entry["commune"], entry["dept"])
        all_prompts.extend(prompts)

    # Output
    output = {
        "generated_at": datetime.now().isoformat(),
        "priority": args.priority,
        "departments": args.dept or list(target_communes.keys()),
        "total_communes_target": sum(len(v) for v in target_communes.values()),
        "already_covered": covered_count,
        "missing_communes": len(missing),
        "total_prompts": len(all_prompts),
        "missing_list": missing[:50],  # First 50 for reference
        "prompts": all_prompts,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary
    print(f"=== COUVERTURE IDF ===")
    print(f"Communes cibles: {output['total_communes_target']}")
    print(f"Déjà couvertes: {sum(covered_count.values())}")
    print(f"Manquantes: {len(missing)}")
    print(f"Prompts générés: {len(all_prompts)}")
    print(f"\nPar département couvert:")
    for dept in sorted(covered_count.keys()):
        total = len(target_communes.get(dept, []))
        cov = covered_count.get(dept, 0)
        print(f"  {dept}: {cov}/{total} couvertes")
    print(f"\nTop communes manquantes (priorité sud):")
    for entry in missing[:20]:
        print(f"  ❌ {entry['commune']} ({entry['dept']})")
    print(f"\nFichier prompts: {output_path}")
    print(f"\nProchaine étape:")
    print(f"  env -u HTTP_PROXY -u HTTPS_PROXY python3 scripts/sourcing/discover_with_tavily.py --prompts {output_path}")


if __name__ == "__main__":
    main()