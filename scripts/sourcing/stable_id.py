#!/usr/bin/env python3
from common import stable_id, norm_text, norm_site, slug
import argparse

def source_record_id(source_url, raw_name='', raw_address=''): return stable_id('src', source_url, raw_name, raw_address)
def candidate_id(name, city='', address='', source_url=''): return stable_id('cand', name, city, address, source_url)
def venue_id(name, city='', address='', lat=None, lon=None):
    loc = address or (f"{round(float(lat),4)},{round(float(lon),4)}" if lat not in (None,'') and lon not in (None,'') else city)
    return stable_id('venue', name, city, loc)
def dedupe_key(name, city='', address='', website=''):
    site=norm_site(website)
    return site or '|'.join([norm_text(name), norm_text(city), slug(address,40)])
if __name__ == '__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('name'); ap.add_argument('--city',default=''); ap.add_argument('--address',default=''); ap.add_argument('--url',default='')
    a=ap.parse_args(); print('candidate_id=', candidate_id(a.name,a.city,a.address,a.url)); print('venue_id=', venue_id(a.name,a.city,a.address)); print('dedupe_key=', dedupe_key(a.name,a.city,a.address,a.url))
