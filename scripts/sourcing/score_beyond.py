#!/usr/bin/env python3
from common import blank, load_taxonomy, norm_text
import argparse, json

def as_list(v):
    if isinstance(v, list): return v
    if not v: return []
    return [x.strip() for x in str(v).split('|') if x.strip()]
def score_candidate(c, taxonomy=None):
    t=taxonomy or load_taxonomy(); reasons=[]; score=int(t.get('scoring',{}).get('beyond_fit',{}).get('base',30))
    for tag in as_list(c.get('activity_tags')):
        w=int(t.get('activity_tags',{}).get(tag,0)); score+=w; 
        if w: reasons.append(f"activité {tag} {w:+d}")
    for tag in as_list(c.get('space_tags')):
        w=int(t.get('space_tags',{}).get(tag,0)); score+=w
        if w: reasons.append(f"espace {tag} {w:+d}")
    for tag in as_list(c.get('constraints_tags')):
        w=int(t.get('constraints_tags',{}).get(tag,0)); score+=w
        if w: reasons.append(f"contrainte {tag} {w:+d}")
    cat=c.get('category') or c.get('category_guess') or ''
    w=int(t.get('categories',{}).get(cat,0)); score+=w
    if w: reasons.append(f"catégorie {cat} {w:+d}")
    evidence=norm_text(' '.join(str(c.get(k,'')) for k in ('description','evidence_text','name','category')))
    for kw in t.get('rules',{}).get('evidence_keywords_positive',[]):
        if norm_text(kw) in evidence: score+=4; reasons.append(f"preuve + {kw}")
    for kw in t.get('rules',{}).get('evidence_keywords_negative',[]):
        if norm_text(kw) in evidence: score-=8; reasons.append(f"preuve - {kw}")
    score=max(0,min(100,score))
    conf_map=t.get('scoring',{}).get('confidence_score',{})
    conf=str(c.get('source_confidence') or '').lower() or str(t.get('source_types',{}).get(c.get('source_type',''),'unknown'))
    confidence_score=int(conf_map.get(conf, conf_map.get('unknown',25)))
    action=0
    aw=t.get('scoring',{}).get('actionability',{})
    if not blank(c.get('contact')): action+=int(aw.get('contact',25)); reasons.append('contact direct')
    if not blank(c.get('price_text')): action+=int(aw.get('price',15)); reasons.append('prix connu')
    if not blank(c.get('capacity_text')) or c.get('capacity_max'): action+=int(aw.get('capacity',15)); reasons.append('capacité connue')
    if not blank(c.get('address')): action+=int(aw.get('address',20)); reasons.append('adresse')
    if not blank(c.get('website')): action+=int(aw.get('website',10)); reasons.append('site web')
    if c.get('source_type') in ('official','municipal','studio_website'): action+=int(aw.get('official_source',15)); reasons.append('source officielle/directe')
    return {'fit_beyond_score':score,'confidence_score':min(100,action if False else confidence_score),'actionability_score':min(100,action),'score_reasons':reasons[:18]}
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('json_file', nargs='?'); a=ap.parse_args()
    obj=json.load(open(a.json_file,encoding='utf-8')) if a.json_file else {'name':'Studio danse démo','category':'studio_danse','activity_tags':['dance','movement'],'space_tags':['open_floor','wood_floor'],'contact':'demo@example.com','price_text':'30€/h','address':'Paris','source_type':'studio_website'}
    print(json.dumps(score_candidate(obj),ensure_ascii=False,indent=2))
