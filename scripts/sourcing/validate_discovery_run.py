#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

REQUIRED_OBS = ['schema_version','observation_id','run_id','provider','discovered_at','source_url']
REQUIRED_FE = ['schema_version','field_evidence_id','observation_id','field_name','value_raw','evidence_url','extraction_method','confidence','extracted_at']
FIELD_NAMES = {'address','contact','price','capacity','rental_possible','surface','website','specific_rental_page'}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate_run(run_dir: Path) -> dict:
    observations = load(run_dir/'observations.json')
    evidence = load(run_dir/'field_evidence.json')
    errors = []
    obs_ids = set()
    for i, o in enumerate(observations, 1):
        for k in REQUIRED_OBS:
            if not str(o.get(k,'')).strip():
                errors.append({'file':'observations.json','index':i,'id':o.get('observation_id',''), 'error':f'missing {k}'})
        if not str(o.get('observation_id','')).startswith('obs_'):
            errors.append({'file':'observations.json','index':i,'id':o.get('observation_id',''), 'error':'bad observation_id prefix'})
        if o.get('observation_id') in obs_ids:
            errors.append({'file':'observations.json','index':i,'id':o.get('observation_id',''), 'error':'duplicate observation_id'})
        obs_ids.add(o.get('observation_id'))
    fe_ids = set()
    for i, e in enumerate(evidence, 1):
        for k in REQUIRED_FE:
            if not str(e.get(k,'')).strip():
                errors.append({'file':'field_evidence.json','index':i,'id':e.get('field_evidence_id',''), 'error':f'missing {k}'})
        if not str(e.get('field_evidence_id','')).startswith('fe_'):
            errors.append({'file':'field_evidence.json','index':i,'id':e.get('field_evidence_id',''), 'error':'bad field_evidence_id prefix'})
        if e.get('field_evidence_id') in fe_ids:
            errors.append({'file':'field_evidence.json','index':i,'id':e.get('field_evidence_id',''), 'error':'duplicate field_evidence_id'})
        fe_ids.add(e.get('field_evidence_id'))
        if e.get('observation_id') not in obs_ids:
            errors.append({'file':'field_evidence.json','index':i,'id':e.get('field_evidence_id',''), 'error':'unknown observation_id'})
        if e.get('field_name') not in FIELD_NAMES:
            errors.append({'file':'field_evidence.json','index':i,'id':e.get('field_evidence_id',''), 'error':'unknown field_name'})
    report = {
        'run_dir': str(run_dir),
        'valid': not errors,
        'errors_count': len(errors),
        'errors': errors[:50],
        'observations': len(observations),
        'field_evidence': len(evidence),
        'observations_by_provider': dict(Counter(o.get('provider','') for o in observations)),
        'field_evidence_by_field': dict(Counter(e.get('field_name','') for e in evidence)),
        'with_specific_rental_page': sum(1 for o in observations if str(o.get('specific_rental_page_url','')).strip()),
        'with_content_hash': sum(1 for o in observations if str(o.get('content_sha256','')).strip()),
    }
    (run_dir/'schema_validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    ap=argparse.ArgumentParser(description='Validate discovery run observations/field evidence consistency.')
    ap.add_argument('run_dir')
    a=ap.parse_args()
    print(json.dumps(validate_run(Path(a.run_dir)), ensure_ascii=False, indent=2))

if __name__=='__main__':
    main()
