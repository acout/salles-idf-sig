#!/usr/bin/env python3
from common import blank, stable_id, now_iso
PROTECTED_STATUSES={'rejected','used','accepted'}
FIELD_TO_OVERRIDE={'canonical_contact':'contactOverride','canonical_price_text':'priceOverride','canonical_capacity_text':'capacityOverride','canonical_address':'addressOverride'}

def decide_field_update(venue, overlay, field, suggested_value, candidate_id='', source_url='', evidence_text='', confidence='unknown'):
    """Return {action, reason, suggested_update?}. Never mutates inputs."""
    if blank(suggested_value): return {'action':'noop','reason':'suggested value blank'}
    status=(overlay or {}).get('status','')
    overrides=(overlay or {}).get('overrides') or {}
    ov_key=FIELD_TO_OVERRIDE.get(field)
    current=str(venue.get(field,'') or '')
    user_override=str(overrides.get(ov_key,'') or '') if ov_key else ''
    if status in PROTECTED_STATUSES:
        return {'action':'suggest','reason':f'protected user status {status}', 'suggested_update':make_suggestion(venue,overlay,field,current,user_override,suggested_value,candidate_id,source_url,evidence_text,confidence)}
    if ov_key and not blank(user_override):
        return {'action':'suggest','reason':'user override exists', 'suggested_update':make_suggestion(venue,overlay,field,current,user_override,suggested_value,candidate_id,source_url,evidence_text,confidence)}
    if blank(current):
        return {'action':'safe_canonical_update','reason':'canonical empty and no user override','field':field,'value':suggested_value}
    if str(current).strip()==str(suggested_value).strip(): return {'action':'noop','reason':'same value'}
    return {'action':'suggest','reason':'canonical already has value', 'suggested_update':make_suggestion(venue,overlay,field,current,user_override,suggested_value,candidate_id,source_url,evidence_text,confidence)}

def make_suggestion(venue, overlay, field, current, user_override, suggested_value, candidate_id, source_url, evidence_text, confidence):
    vid=venue.get('venue_id') or venue.get('id') or venue.get('name') or 'unknown'
    return {'suggested_update_id': stable_id('sug',vid,field,suggested_value,source_url),'venue_id':vid,'candidate_id':candidate_id,'field':field,'current_canonical_value':current,'current_user_override_value':user_override,'suggested_value':suggested_value,'source_url':source_url,'evidence_text':evidence_text,'confidence':confidence or 'unknown','status':'pending','created_at':now_iso()}
if __name__=='__main__':
    demo_v={'venue_id':'venue_demo','canonical_contact':''}; demo_o={'status':'new','overrides':{}}
    print(decide_field_update(demo_v,demo_o,'canonical_contact','contact@example.com'))
    print(decide_field_update(demo_v,{'status':'new','overrides':{'contactOverride':'Marie 06'}},'canonical_contact','standard@example.com'))
