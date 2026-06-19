#!/usr/bin/env python3
import csv, json, os, re, time, urllib.parse, urllib.request
from pathlib import Path
for _k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):
    os.environ.pop(_k, None)

ROOT=Path('/home/antho/salles-idf-sig')
DATA=ROOT/'data'
PUBLIC=ROOT/'public'
DATA.mkdir(exist_ok=True); PUBLIC.mkdir(exist_ok=True)

venues = [
# Paris
{'name':'Forum des images','city':'Paris','department':'75','address':'2 rue du Cinéma, Forum des Halles, 75001 Paris','capacity_text':'100, 274, 444 places ; espaces réception 120 à 440 personnes','website':'https://www.forumdesimages.fr','contact':'privatisations@forumdesimages.fr ; 01 44 76 62 16','category':'centre culturel / cinéma','source_url':'https://www.forumdesimages.fr/privatisation-despaces','pros':['central','auditoriums + foyers','contact direct'],'cons':['plutôt semaine','certaines jauges >300'],'confidence':'high'},
{'name':'Maison de la Chimie','city':'Paris','department':'75','address':'28 rue Saint-Dominique, 75007 Paris','capacity_text':'salles 15 à 300 personnes ; amphithéâtre 216 places','website':'https://maisondelachimie.com','contact':'+33 1 40 62 27 00 ; formulaire devis','category':'centre de conférences','source_url':'https://maisondelachimie.com/evenementiel-paris/nos-espaces','pros':['institutionnel','nombreuses salles','conférences/séminaires'],'cons':['tarifs sur devis','choix salle à cadrer'],'confidence':'high'},
{'name':'Musée national de la Marine - L’Astrolab','city':'Paris','department':'75','address':'17 place du Trocadéro et du 11 Novembre, 75116 Paris','capacity_text':'auditorium 200 places + foyer + salles réunion','website':'https://www.musee-marine.fr','contact':'formulaire sur site','category':'musée / auditorium','source_url':'https://www.musee-marine.fr/professionnels/entreprise/location-despace.html','pros':['auditorium cible','cadre rénové','Trocadéro'],'cons':['contact direct à confirmer','contraintes musée'],'confidence':'high'},
{'name':'Musée Rodin','city':'Paris','department':'75','address':'77 rue de Varenne, 75007 Paris','capacity_text':'2 à 1500 invités selon espaces','website':'https://www.musee-rodin.fr','contact':'formulaire page privatisation','category':'musée / jardin','source_url':'https://www.musee-rodin.fr/professionnels/location-despaces','pros':['patrimonial','jardin','prestige'],'cons':['créneaux contraints','premium'],'confidence':'high'},
{'name':'La Gaîté Lyrique','city':'Paris','department':'75','address':'3 bis rue Papin, 75003 Paris','capacity_text':'Audito 126 places ; grande salle 304 places conférence','website':'https://www.gaite-lyrique.net','contact':'privatisations@gaite-lyrique.net','category':'centre culturel / auditorium','source_url':'https://www.gaite-lyrique.net/infos-pratiques/le-lieu/grande-salle','pros':['créatif','central','AV avancé'],'cons':['programmation culturelle','grande salle limite >300'],'confidence':'high'},
{'name':'Palais de Tokyo','city':'Paris','department':'75','address':'13 avenue du Président Wilson, 75116 Paris','capacity_text':'espaces 180 à 1300 m²','website':'https://palaisdetokyo.com','contact':'evenementiel@palaisdetokyo.com','category':'centre art contemporain','source_url':'https://palaisdetokyo.com/privatisations','pros':['très identifiable','espaces atypiques','contact direct'],'cons':['certains espaces très grands','contraintes exposition'],'confidence':'high'},
{'name':'Les Salons Hoche','city':'Paris','department':'75','address':'9 avenue Hoche, 75008 Paris','capacity_text':'Salon Élysée jusqu’à 300 cocktail / 250 dîner / 200 théâtre','website':'https://www.salons-hoche.fr','contact':'contact@salons-hoche.fr ; 01 53 53 93 93','category':'salons réception','source_url':'https://www.salons-hoche.fr','pros':['clé en main','prestige','accès Étoile'],'cons':['premium','capacités à confirmer'],'confidence':'high'},
{'name':'Espace Saint-Martin','city':'Paris','department':'75','address':'199 bis rue Saint-Martin, 75003 Paris','capacity_text':'9 salles ; 8 à 350 places','website':'https://www.espacesaintmartin.com','contact':None,'category':'centre congrès / salles','source_url':'https://www.espacesaintmartin.com','pros':['central','modulable','PMR'],'cons':['contact à compléter','auditorium >300'],'confidence':'high'},
{'name':'BnF Richelieu / François-Mitterrand','city':'Paris','department':'75','address':'5 rue Vivienne, 75002 Paris','capacity_text':'Salle Ovale 300 cocktail ; auditoriums 200/350 places','website':'https://www.bnf.fr','contact':'federica.serputi@bnf.fr ; pauline.denis@bnf.fr ; gilles.monfray@bnf.fr','category':'institution culturelle','source_url':'https://www.bnf.fr/fr/location-despaces','pros':['patrimonial + contemporain','auditoriums cible','contacts nominatifs'],'cons':['multi-sites','contraintes horaires'],'confidence':'high'},
{'name':'Espace Cléry','city':'Paris','department':'75','address':'17 rue de Cléry, 75002 Paris','capacity_text':'20 salles ; Verrière jusqu’à 150 assis / 200 personnes','website':'https://www.formeret.fr','contact':'contact@formeret.fr ; 01 42 46 79 77','category':'salles réunion / verrière','source_url':'https://www.formeret.fr/en/our-spaces/clery','pros':['central','sous-commissions','verrière'],'cons':['numéros à confirmer','sur devis'],'confidence':'high'},
{'name':'Pavillon Wagram','city':'Paris','department':'75','address':'47 avenue de Wagram, 75017 Paris','capacity_text':'270 théâtre ; 290 repas ; 600 cocktail','website':'https://pavillonwagram.com','contact':'pavillonwagram@lieuxdemotions.fr ; 01 49 29 50 50','category':'hôtel particulier / réception','source_url':'https://pavillonwagram.com','pros':['près Étoile','art déco','270 théâtre'],'cons':['premium','cocktail >300'],'confidence':'high'},
{'name':'La Caserne','city':'Paris','department':'75','address':'12 rue Philippe de Girard, 75010 Paris','capacity_text':'espaces 80 à 880 m² ; talkroom 176 m², rooftop 280 m²','website':'https://www.lacaserneparis.com','contact':'formulaire de devis','category':'tiers-lieu / événement responsable','source_url':'https://www.lacaserneparis.com/privatisation-espaces-la-caserne','pros':['hybride/engagé','rooftop','nombreux espaces'],'cons':['capacités personnes à confirmer','formulaire'],'confidence':'high'},
# Petite couronne
{'name':'Hangar Y','city':'Meudon','department':'92','address':'9 avenue de Trivaux, 92190 Meudon','capacity_text':'espaces notamment 25 à 140 personnes ; jauge globale plus large','website':'https://hangar-y.com/privatisation','contact':'privatisations@hangar-y.com','category':'patrimoine / atypique','source_url':'https://hangar-y.com/privatisation','pros':['lieu patrimonial','proche Paris','formats 25-140'],'cons':['certaines jauges >300','premium'],'confidence':'high'},
{'name':'Paris La Défense Arena - salons','city':'Nanterre','department':'92','address':'99 jardins de l’Arche, 92000 Nanterre','capacity_text':'10 espaces 90 à 910 m² ; 90 à 500 personnes','website':'https://www.parisladefense-arena.com/convention-et-seminaires','contact':'contact via site officiel','category':'arena / salons corporate','source_url':'https://www.parisladefense-arena.com/convention-et-seminaires','pros':['salons modulables','technique','La Défense'],'cons':['certains espaces >300','corporate'],'confidence':'high'},
{'name':'Domaine national de Saint-Cloud - espace de l’Institut','city':'Saint-Cloud','department':'92','address':'Domaine national de Saint-Cloud, 92210 Saint-Cloud','capacity_text':'30 assis / 50 debout + jardin privatif','website':'https://www.domaine-saint-cloud.fr','contact':'01 44 61 20 30 ; location@monuments-nationaux.fr','category':'domaine / patrimoine','source_url':'https://www.domaine-saint-cloud.fr/privatisation/evenements-professionnels-cocktails-seminaires','pros':['cadre fort','jardin privatif','petit format'],'cons':['capacité limitée','contraintes patrimoniales'],'confidence':'high'},
{'name':'MAC VAL','city':'Vitry-sur-Seine','department':'94','address':'Place de la Libération, 94400 Vitry-sur-Seine','capacity_text':'auditorium 146 places + hall/salon/jardin','website':'https://www.macval.fr/Privatiser','contact':'01 43 91 64 20 ; contact@macval.fr','category':'musée / auditorium','source_url':'https://www.macval.fr/Privatiser','pros':['lieu culturel atypique','auditorium cible','espaces complémentaires'],'cons':['programmation','détails par espace à confirmer'],'confidence':'high'},
{'name':'Château de Vincennes','city':'Vincennes','department':'94','address':'Avenue de Paris, 94300 Vincennes','capacity_text':'Sainte-Chapelle 200 assis / 250 debout ; casemates 25-80','website':'https://www.chateau-de-vincennes.fr','contact':'contact via page officielle','category':'monument national','source_url':'https://www.chateau-de-vincennes.fr/privatisation/evenements-professionnels-cocktails-seminaires','pros':['historique','portes de Paris','25-250 personnes'],'cons':['contraintes monument','contact direct à compléter'],'confidence':'high'},
{'name':'La Cité Fertile','city':'Pantin','department':'93','address':'14 avenue Édouard Vaillant, 93500 Pantin','capacity_text':'espaces privatisables ; certains formats <200 ; global jusqu’à 2000','website':'https://citefertile.com/privatisations','contact':'01 48 43 04 60 ; contact@citefertile.com','category':'tiers-lieu','source_url':'https://citefertile.com/privatisations','pros':['tiers-lieu emblématique','nombreux formats','contact clair'],'cons':['capacités à confirmer','forte demande'],'confidence':'medium'},
{'name':'La Marbrerie','city':'Montreuil','department':'93','address':'21 rue Alexis Lepère, 93100 Montreuil','capacity_text':'650 debout ; 330 assises','website':'https://lamarbrerie.fr/privatisation','contact':'01 43 62 71 19 ; privatisation@lamarbrerie.fr','category':'lieu culturel / industriel','source_url':'https://lamarbrerie.fr/privatisation','pros':['industriel atypique','proche métro','grande salle'],'cons':['330 assis limite >300','programmation'],'confidence':'high'},
{'name':'Magasins Généraux','city':'Pantin','department':'93','address':'1 rue de l’Ancien Canal, 93500 Pantin','capacity_text':'capacité à confirmer ; privatisation événements pro','website':'https://magasinsgeneraux.com/partenaires','contact':'hello@magasinsgeneraux.com','category':'centre création / lieu culturel','source_url':'https://magasinsgeneraux.com/partenaires','pros':['bord canal','créatif','contact officiel'],'cons':['capacité à confirmer','sélection/devis'],'confidence':'medium'},
{'name':'Dock B','city':'Pantin','department':'93','address':'1 place de la Pointe, 93500 Pantin','capacity_text':'750 m² intérieur ; convention env. 150 personnes selon sources','website':'https://dockbpantin.com/privatisation','contact':'eliott@dockbpantin.com ; 01 41 71 49 69','category':'lieu hybride / restaurant','source_url':'https://dockbpantin.com/privatisation','pros':['hybride','format 150','Pantin canal'],'cons':['capacités officielles à confirmer','cocktail >300'],'confidence':'medium'},
# Grande couronne seeds from web searches
{'name':'Château de Janvry','city':'Janvry','department':'91','address':'Rue du Château, 91640 Janvry','capacity_text':'séminaires et journées d’étude ; salons, ancienne cuisine, jardins ; domaine 200 ha','website':'https://www.chateaudejanvry.com','contact':'+33 6 35 45 58 96 ; contact@chateaudejanvry.com','category':'château / domaine nature','source_url':'https://www.chateaudejanvry.com','pros':['35 min sud Paris','nature','privatisation château'],'cons':['capacité précise à confirmer','transport collectif à vérifier'],'confidence':'medium'},
{'name':'Résidence Château du Mée','city':'Le Mée-sur-Seine','department':'77','address':'571 avenue Jean Monnet, 77350 Le Mée-sur-Seine','capacity_text':'salles de séminaires jusqu’à 80 personnes assises','website':'https://www.rcdm.fr','contact':'contact via site officiel','category':'hôtel / château séminaire','source_url':'https://www.rcdm.fr/fr/seminaires.html','pros':['accessible Paris','hébergement/restauration','80 assis'],'cons':['capacité limitée','contact direct à compléter'],'confidence':'high'},
{'name':'Château des Bondons','city':'La Ferté-sous-Jouarre','department':'77','address':'47-49 rue des Bondons, 77260 La Ferté-sous-Jouarre','capacity_text':'salles pour séminaires entreprise ; capacité à confirmer','website':'https://www.chateaudesbondons.com','contact':'contact via site officiel','category':'château hôtel / séminaire','source_url':'https://www.chateaudesbondons.com/fr/seminaire-seine-et-marne.html','pros':['site officiel séminaire','cadre château','équipe dédiée'],'cons':['jauge précise à vérifier','plus éloigné de Paris'],'confidence':'medium'},
{'name':'Domaine des Hirondelles','city':'Hameau de Craches / Rambouillet Territoires','department':'78','address':'25 rue de la Libération, 78125 La Boissière-École','capacity_text':'200 assises / 300 cocktail selon Office de Tourisme Rambouillet','website':'https://www.rambouillet-tourisme.fr','contact':'+33 1 34 83 05 51 ; +33 6 45 96 02 22','category':'domaine / réception','source_url':'https://www.rambouillet-tourisme.fr/nos-sejours/sorties-en-groupes/les-lieux-de-receptions-et-seminaires-de-rambouillet-territoires','pros':['200-300 dans cible','source OT','nature Yvelines'],'cons':['site direct à retrouver','accès depuis Paris à vérifier'],'confidence':'medium'},
]

def slug(s):
    s = re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')
    return s[:60]

def cap_nums(txt):
    nums=[int(x.replace(' ','')) for x in re.findall(r'\b\d{2,4}\b', txt or '')]
    nums=[n for n in nums if n<=3000]
    if not nums: return None,None
    return min(nums), max(nums)

def geocode(addr):
    q=urllib.parse.urlencode({'q': addr, 'limit':1})
    url='https://api-adresse.data.gouv.fr/search/?'+q
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'Hermes venue map prototype (local research)'})
        with urllib.request.urlopen(req, timeout=10) as r:
            js=json.load(r)
        if js.get('features'):
            f=js['features'][0]
            lon,lat=f['geometry']['coordinates']
            props=f.get('properties',{})
            return lat,lon,props.get('score'),props.get('label')
    except Exception as e:
        return None,None,None,str(e)
    return None,None,None,None

rows=[]; features=[]
for i,v in enumerate(venues,1):
    lat,lon,gscore,glabel=geocode(v['address'])
    time.sleep(0.12)
    cmin,cmax=cap_nums(v['capacity_text'])
    contact_present=bool(v.get('contact'))
    quality=0
    if lat and lon: quality+=25
    if contact_present: quality+=20
    if v['confidence']=='high': quality+=20
    elif v['confidence']=='medium': quality+=12
    if cmax: quality+=10
    if v.get('source_url'): quality+=15
    fit=0
    if cmax and cmin and cmin<=300 and cmax>=20: fit+=30
    if v['department'] in {'75','92','93','94'}: fit+=15
    if contact_present: fit+=15
    if v['confidence']=='high': fit+=15
    if any(x in v['category'] for x in ['tiers-lieu','culturel','musée','château','domaine','auditorium']): fit+=15
    if cmax and cmax<=350: fit+=10
    rid=f"idf-{i:03d}-{slug(v['name'])}"
    rec={
        'id':rid,'name':v['name'],'category':v['category'],'address':v['address'],'city':v['city'],'department':v['department'],
        'lat':lat,'lon':lon,'geocode_score':gscore,'geocode_label':glabel,
        'capacity_text':v['capacity_text'],'capacity_min':cmin,'capacity_max':cmax,
        'website':v['website'],'contact':v.get('contact') or '',
        'pros':' | '.join(v['pros']),'cons':' | '.join(v['cons']),
        'source_url':v['source_url'],'confidence':v['confidence'],'quality_score':quality,'fit_score':fit,'last_checked':'2026-06-19'
    }
    rows.append(rec)
    if lat and lon:
        features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[lon,lat]},'properties':rec})

fields=list(rows[0].keys())
with open(DATA/'salles_idf.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
with open(PUBLIC/'salles_idf.geojson','w',encoding='utf-8') as f:
    json.dump({'type':'FeatureCollection','features':features},f,ensure_ascii=False,indent=2)

html = r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carte salles IDF</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif}#map{height:100vh}.panel{position:absolute;z-index:1000;top:10px;left:10px;background:white;padding:12px;border-radius:12px;box-shadow:0 2px 12px #0002;max-width:360px}.panel h1{font-size:17px;margin:0 0 8px}.filters{display:flex;gap:6px;flex-wrap:wrap}.filters button{border:1px solid #ddd;background:#f7f7f7;border-radius:999px;padding:6px 9px}.filters button.active{background:#111;color:white}.legend{font-size:12px;margin-top:8px;color:#555}.popup{max-width:360px}.popup h3{margin:0 0 6px}.tag{display:inline-block;background:#eef;border-radius:6px;padding:2px 5px;margin:2px;font-size:12px}.score{font-weight:700}</style></head><body><div id="map"></div><div class="panel"><h1>Salles IDF — prospection v0</h1><div id="count"></div><div class="filters"><button data-dept="all" class="active">Tous</button><button data-dept="75">75</button><button data-dept="92">92</button><button data-dept="93">93</button><button data-dept="94">94</button><button data-dept="77">77</button><button data-dept="78">78</button><button data-dept="91">91</button></div><div class="legend">Couleur = fit score. Données issues collecte web + géocodage BAN. À qualifier commercialement avant contact.</div></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const map=L.map('map').setView([48.8566,2.3522],10);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map);let layer=L.layerGroup().addTo(map), data=null, current='all';
function color(s){return s>=80?'#0a7':s>=65?'#7c3':s>=50?'#fb0':'#f60'}
function render(){layer.clearLayers();let shown=0;data.features.forEach(f=>{const p=f.properties;if(current!=='all'&&p.department!==current)return;shown++;const m=L.circleMarker([p.lat,p.lon],{radius:8,color:'#222',weight:1,fillColor:color(p.fit_score),fillOpacity:.85}).addTo(layer);m.bindPopup(`<div class="popup"><h3>${p.name}</h3><div><span class="tag">${p.department}</span><span class="tag">${p.category}</span><span class="tag score">fit ${p.fit_score}/100</span><span class="tag">qualité ${p.quality_score}/100</span></div><p><b>Adresse</b>: ${p.address}</p><p><b>Capacité</b>: ${p.capacity_text}</p><p><b>Contact</b>: ${p.contact||'à compléter'}</p><p><b>Pros</b>: ${p.pros}</p><p><b>Cons</b>: ${p.cons}</p><p><a href="${p.website}" target="_blank">site</a> · <a href="${p.source_url}" target="_blank">source</a></p></div>`)});document.getElementById('count').textContent=`${shown} lieux affichés / ${data.features.length} géocodés`;}
fetch('salles_idf.geojson').then(r=>r.json()).then(j=>{data=j;render();});document.querySelectorAll('button[data-dept]').forEach(b=>b.onclick=()=>{document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');current=b.dataset.dept;render();});
</script></body></html>'''
(PUBLIC/'index.html').write_text(html,encoding='utf-8')
print(json.dumps({'rows':len(rows),'geocoded':len(features),'csv':str(DATA/'salles_idf.csv'),'geojson':str(PUBLIC/'salles_idf.geojson'),'html':str(PUBLIC/'index.html')},ensure_ascii=False,indent=2))
