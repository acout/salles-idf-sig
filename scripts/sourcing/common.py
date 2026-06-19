from __future__ import annotations
import csv, hashlib, json, re, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
ROOT = Path(__file__).resolve().parents[2]

def now_iso(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def strip_accents(s): return ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn')
def norm_text(s): return re.sub(r'[^a-z0-9]+',' ', strip_accents(str(s or '').lower())).strip()
def slug(s, max_len=64): return re.sub(r'[^a-z0-9]+','-', norm_text(s)).strip('-')[:max_len] or 'unknown'
def short_hash(*parts, n=10): return hashlib.sha1('|'.join(str(p or '') for p in parts).encode('utf-8')).hexdigest()[:n]
def stable_id(prefix, *parts): return f"{prefix}_{slug(parts[0] if parts else prefix, 36)}_{short_hash(*parts)}"
def blank(v):
    t=str(v or '').strip().lower()
    return not t or t in {'—','-','n/a','na','non renseigné','non renseigne','à confirmer','a confirmer','unknown','inconnu'} or 'à confirmer' in t or 'a confirmer' in t
def norm_site(url):
    try:
        u=urlparse(str(url or '').strip())
        host=(u.netloc or u.path).lower().replace('www.','')
        path=(u.path if u.netloc else '').rstrip('/')
        return host+path
    except Exception: return ''
def read_records(path):
    p=Path(path)
    if p.suffix.lower()=='.json':
        data=json.loads(p.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else data.get('records') or data.get('candidates') or [data]
    with p.open(newline='', encoding='utf-8') as f: return list(csv.DictReader(f))
def write_csv(path, rows, fields=None):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fields=fields or sorted({k for r in rows for k in r})
    with path.open('w', newline='', encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
def load_taxonomy(path=None):
    # Minimal parser for config/sourcing_taxonomy.yaml. Supports top-level sections with scalar maps/lists.
    path=Path(path or ROOT/'config/sourcing_taxonomy.yaml')
    out={}; current=None; parent_stack=[]
    for raw in path.read_text(encoding='utf-8').splitlines():
        line=raw.split('#',1)[0].rstrip()
        if not line: continue
        indent=len(raw)-len(raw.lstrip(' '))
        text=line.strip()
        if indent==0 and text.endswith(':'):
            current=text[:-1]; out[current]={}; parent_stack=[current]; continue
        if current is None: continue
        if ':' in text:
            k,v=text.split(':',1); k=k.strip(); v=v.strip()
            if indent==2 and not v:
                out[current][k]={}; parent_stack=[current,k]
            elif indent>=4 and len(parent_stack)>=2:
                out[parent_stack[0]][parent_stack[1]][k]=parse_scalar(v)
            else:
                out[current][k]=parse_scalar(v)
    return out
def parse_scalar(v):
    v=v.strip()
    if v.startswith('[') and v.endswith(']'): return [x.strip() for x in v[1:-1].split(',') if x.strip()]
    try: return int(v)
    except Exception: pass
    try: return float(v)
    except Exception: pass
    return v.strip('"\'')
