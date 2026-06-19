#!/usr/bin/env python3
from common import read_records, norm_text, norm_site
import argparse, json, math

def rounded_coord(v):
    try: return round(float(v),4)
    except Exception: return None
def match_candidate(candidate, venues):
    cn=norm_text(candidate.get('name')); ccity=norm_text(candidate.get('city')); csite=norm_site(candidate.get('website') or candidate.get('source_url'))
    clat,clon=rounded_coord(candidate.get('lat')),rounded_coord(candidate.get('lon'))
    matches=[]
    for v in venues:
        vn=norm_text(v.get('canonical_name') or v.get('name')); vcity=norm_text(v.get('city')); vsite=norm_site(v.get('canonical_website') or v.get('website'))
        score=0; reasons=[]
        if csite and vsite and csite==vsite: score+=70; reasons.append('same_website')
        if cn and vn and (cn==vn or cn in vn or vn in cn): score+=45; reasons.append('name_close')
        if ccity and vcity and ccity==vcity: score+=15; reasons.append('same_city')
        vlat,vlon=rounded_coord(v.get('lat')),rounded_coord(v.get('lon'))
        if clat is not None and clon is not None and clat==vlat and clon==vlon: score+=35; reasons.append('same_coord_rounded')
        if score>=60: matches.append({'venue_id':v.get('venue_id') or v.get('id') or v.get('name'),'score':score,'reasons':reasons})
    return sorted(matches,key=lambda x:x['score'],reverse=True)[:5]
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('candidates'); ap.add_argument('venues'); a=ap.parse_args()
    cands=read_records(a.candidates); venues=read_records(a.venues)
    print(json.dumps([{**c,'matches':match_candidate(c,venues)} for c in cands],ensure_ascii=False,indent=2))
