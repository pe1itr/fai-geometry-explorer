"""Zelfstandige bereikbaarheidkaart voor Single Station Mode."""

from __future__ import annotations

import json
from pathlib import Path

from .map_export import _load_land_polygons
from .single_station import ReachableRegionPoint, SingleSearchResult


def write_single_station_map(
    result: SingleSearchResult, locator: str, output_path: str | Path
) -> Path:
    """Schrijf bereikbare grondgebieden als zelfstandig lokaal HTML/SVG."""

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    bounds = _bounds(result)
    boundary_source, land_polygons = _load_land_polygons(bounds)
    payload = {
        "locator": locator.upper(),
        "station": {
            "latitude": result.station.latitude_deg,
            "longitude": result.station.longitude_deg,
        },
        "modelDate": result.model_date.isoformat(),
        "modelVersion": result.model_version,
        "gridStepKm": result.config.grid_step_km,
        "heightKm": result.config.heights_km[0],
        "minElevationDeg": result.config.min_elevation_deg,
        "azimuth": result.config.antenna_azimuth_deg,
        "azimuthTolerance": result.config.azimuth_tolerance_deg,
        "visibleScatterCount": result.visible_scatter_count,
        "acceptedScatterCount": result.accepted_scatter_count,
        "rawEndpointCount": result.reverse_endpoint_count,
        "reachableCount": len(result.reachable_points),
        "skedScore": (
            result.sked_validation.score_total
            if result.sked_validation is not None
            else None
        ),
        "boundarySource": boundary_source,
        "landPolygons": land_polygons,
        "points": [_point_payload(point) for point in result.reachable_points],
    }
    data_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    path.write_text(_html_document(data_json), encoding="utf-8")
    return path


def _bounds(result: SingleSearchResult) -> tuple[float, float, float, float]:
    latitudes = [result.station.latitude_deg]
    longitudes = [result.station.longitude_deg]
    for point in result.reachable_points:
        latitudes.extend((point.latitude_deg, point.scatter_latitude_deg))
        longitudes.extend((point.longitude_deg, point.scatter_longitude_deg))
    min_lat, max_lat = min(latitudes), max(latitudes)
    min_lon, max_lon = min(longitudes), max(longitudes)
    lat_pad = max((max_lat - min_lat) * 0.06, 0.25)
    lon_pad = max((max_lon - min_lon) * 0.06, 0.25)
    return min_lat - lat_pad, max_lat + lat_pad, min_lon - lon_pad, max_lon + lon_pad


def _point_payload(point: ReachableRegionPoint) -> dict[str, float]:
    return {
        "lat": point.latitude_deg,
        "lon": point.longitude_deg,
        "score": point.score_total,
        "scatterLat": point.scatter_latitude_deg,
        "scatterLon": point.scatter_longitude_deg,
        "height": point.scatter_height_km,
        "az1": point.azimuth_1_deg,
        "el1": point.elevation_1_deg,
        "distance1": point.distance_1_km,
        "error1": point.aspect_error_1_deg,
        "az2": point.counterstation_azimuth_deg,
        "el2": point.counterstation_elevation_deg,
        "distance2": point.counterstation_distance_km,
        "error2": point.counterstation_aspect_error_deg,
    }


def _html_document(data_json: str) -> str:
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FAI-bereikbaarheid</title>
<style>
  :root{{font-family:Arial,Helvetica,sans-serif}}*{{box-sizing:border-box}}
  body{{margin:0;background:#e8edf2;color:#172033}}
  header{{padding:14px 20px;background:#172033;color:white}}header h1{{margin:0;font-size:20px}}
  header p{{margin:5px 0 0;font-size:13px;color:#cbd5e1}}
  main{{display:grid;grid-template-columns:minmax(620px,1fr)340px;gap:12px;padding:12px;min-height:calc(100vh - 75px)}}
  .map-card,.panel{{background:white;border:1px solid #cbd5e1;border-radius:7px;box-shadow:0 1px 4px #0f17221f}}
  .map-card{{padding:8px;display:flex;align-items:center;min-width:0}}
  svg{{width:100%;height:auto;max-height:calc(100vh - 100px);background:#dceff7}}
  .panel{{padding:15px;overflow:auto}}.panel h2{{font-size:16px;margin:0 0 8px}}
  .panel h3{{font-size:14px;margin:17px 0 6px;border-bottom:1px solid #d7dee7;padding-bottom:4px}}
  .panel p{{font-size:12px;line-height:1.4;margin:5px 0}}.panel table{{width:100%;border-collapse:collapse;font-size:12px}}
  .panel td{{padding:4px 3px;border-bottom:1px solid #e5e7eb}}.panel td:first-child{{font-weight:600}}
  input[type=range]{{width:100%}}.legend{{height:13px;border-radius:3px;margin:5px 0;background:linear-gradient(90deg,#2563eb,#06b6d4,#fde047,#dc2626)}}
  .muted{{color:#64748b}}.border{{fill:#dceff7;stroke:#334155;stroke-width:1.4}}
  .land{{fill:#e5e7eb;stroke:#94a3b8;stroke-width:.8}}.grid-line{{stroke:#bac6d3;stroke-width:1}}
  .grid-label{{fill:#475569;font-size:12px}}.reachable{{cursor:pointer;stroke:none}}
  .maidenhead-label{{fill:#64748b;font-size:10px;font-weight:700;opacity:.58;pointer-events:none}}
  .reachable:hover{{stroke:#111827;stroke-width:2;r:5}}.station{{fill:#15803d;stroke:white;stroke-width:2}}
  .label{{font-size:14px;font-weight:700;paint-order:stroke;stroke:white;stroke-width:4;stroke-linejoin:round}}
  .path-a{{stroke:#15803d;stroke-width:2.5;stroke-dasharray:7 4;fill:none}}
  .path-b{{stroke:#7e22ce;stroke-width:2.5;stroke-dasharray:7 4;fill:none}}
  .sector{{fill:#f59e0b22;stroke:#d97706;stroke-width:1.5;stroke-dasharray:5 4}}
  .best-scatter{{fill:#111827;font-size:27px;font-weight:bold;text-anchor:middle;paint-order:stroke;stroke:white;stroke-width:4}}
  .best-endpoint{{fill:#7e22ce;stroke:white;stroke-width:2}}
  @media(max-width:900px){{main{{grid-template-columns:1fr}}svg{{max-height:none}}}}
  @media print{{body{{background:white}}header{{background:white;color:black}}header p{{color:#334155}}main{{display:block;padding:0}}.map-card,.panel{{box-shadow:none;border:0}}}}
</style></head><body>
<header><h1 id="title"></h1><p id="subtitle"></p></header>
<main><section class="map-card"><svg id="map" viewBox="0 0 1000 700">
  <defs><clipPath id="clip"><rect x="65" y="35" width="870" height="600"/></clipPath></defs>
  <rect class="border" x="65" y="35" width="870" height="600"/>
  <g id="land" clip-path="url(#clip)"></g><g id="grid"></g><g id="sector"></g>
  <g id="points"></g><g id="route"></g><g id="markers"></g><g id="labels"></g>
</svg></section><aside class="panel">
  <h2>Bereikbare tegenstationgebieden</h2><p id="counts"></p>
  <label><strong>Minimale absolute geometry match:</strong> <span id="score-value">70%</span></label>
  <input id="score-filter" type="range" min="0" max="100" value="70"><div class="legend"></div>
  <p class="muted">Klik op een gekleurd grondpunt voor het bijbehorende scatterpunt en de antennerichtingen.</p>
  <h3>Beste geometrische route</h3><table id="best-table"></table>
  <h3>Geselecteerd gebied</h3><p id="selection-help" class="muted">Nog geen punt geselecteerd.</p><table id="selected-table"></table>
  <h3>Instellingen</h3><table id="model-table"></table>
  <p class="muted">Dit is geometrische bereikbaarheid, niet de actuele aanwezigheid van FAI.</p>
</aside></main>
<script>
const data={data_json},NS='http://www.w3.org/2000/svg',plot={{left:65,top:35,width:870,height:600}};
const svg=document.getElementById('map'),land=document.getElementById('land'),grid=document.getElementById('grid');
const sector=document.getElementById('sector'),points=document.getElementById('points'),route=document.getElementById('route');
const markers=document.getElementById('markers'),labels=document.getElementById('labels');
document.getElementById('title').textContent=`FAI-bereikbaarheid vanuit ${{data.locator}}`;
document.getElementById('subtitle').textContent=`${{data.modelVersion}} · ${{data.modelDate}} · ${{data.heightKm.toFixed(1)}} km`;
const locations=[data.station,...data.points.flatMap(p=>[{{latitude:p.lat,longitude:p.lon}},{{latitude:p.scatterLat,longitude:p.scatterLon}}])];
let minLat=Math.min(...locations.map(p=>p.latitude)),maxLat=Math.max(...locations.map(p=>p.latitude));
let minLon=Math.min(...locations.map(p=>p.longitude)),maxLon=Math.max(...locations.map(p=>p.longitude));
const latPad=Math.max((maxLat-minLat)*.06,.25),lonPad=Math.max((maxLon-minLon)*.06,.25);
minLat-=latPad;maxLat+=latPad;minLon-=lonPad;maxLon+=lonPad;
const midLat=(minLat+maxLat)/2,lonFactor=Math.cos(midLat*Math.PI/180);
const scale=Math.min(plot.width/((maxLon-minLon)*lonFactor),plot.height/(maxLat-minLat));
const usedWidth=(maxLon-minLon)*lonFactor*scale,usedHeight=(maxLat-minLat)*scale;
const offsetX=plot.left+(plot.width-usedWidth)/2,offsetY=plot.top+(plot.height-usedHeight)/2;
function xy(lat,lon){{return[offsetX+(lon-minLon)*lonFactor*scale,offsetY+(maxLat-lat)*scale]}}
function el(name,attrs,parent=svg){{const n=document.createElementNS(NS,name);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));parent.appendChild(n);return n}}
function txt(x,y,value,klass,parent=svg,anchor='middle'){{const n=el('text',{{x,y,class:klass,'text-anchor':anchor}},parent);n.textContent=value;return n}}
function maidenhead4(lat,lon){{const shiftedLon=Math.min(Math.max(lon+180,0),359.999999),shiftedLat=Math.min(Math.max(lat+90,0),179.999999),fieldLon=Math.floor(shiftedLon/20),fieldLat=Math.floor(shiftedLat/10),squareLon=Math.floor((shiftedLon-fieldLon*20)/2),squareLat=Math.floor(shiftedLat-fieldLat*10);return String.fromCharCode(65+fieldLon)+String.fromCharCode(65+fieldLat)+squareLon+squareLat}}
data.landPolygons.forEach(poly=>{{const d=poly.ring.map((c,i)=>{{const p=xy(c[1],c[0]);return`${{i?'L':'M'}}${{p[0].toFixed(1)}} ${{p[1].toFixed(1)}}`}}).join(' ')+' Z';const s=el('path',{{d,class:'land'}},land);const t=el('title',{{}},s);t.textContent=poly.name}});
const latStep=1,lonStep=2;
for(let lat=Math.ceil(minLat);lat<=maxLat;lat+=latStep){{const y=xy(lat,minLon)[1];el('line',{{x1:offsetX,y1:y,x2:offsetX+usedWidth,y2:y,class:'grid-line'}},grid);txt(offsetX-8,y+4,`${{lat.toFixed(0)}}°`,'grid-label',grid,'end')}}
for(let lon=Math.ceil(minLon/2)*2;lon<=maxLon;lon+=lonStep){{const x=xy(minLat,lon)[0];el('line',{{x1:x,y1:offsetY,x2:x,y2:offsetY+usedHeight,class:'grid-line'}},grid);txt(x,offsetY+usedHeight+18,`${{lon.toFixed(0)}}°`,'grid-label',grid)}}
for(let lat=Math.floor(minLat);lat<maxLat;lat+=1){{for(let lon=Math.floor(minLon/2)*2;lon<maxLon;lon+=2){{const centreLat=lat+.5,centreLon=lon+1;if(centreLat>=minLat&&centreLat<=maxLat&&centreLon>=minLon&&centreLon<=maxLon){{const p=xy(centreLat,centreLon);txt(p[0],p[1]+4,maidenhead4(centreLat,centreLon),'maidenhead-label',grid)}}}}}}
function destination(az,distanceKm){{const r=6371.0088,delta=distanceKm/r,bearing=az*Math.PI/180,lat1=data.station.latitude*Math.PI/180,lon1=data.station.longitude*Math.PI/180;const lat2=Math.asin(Math.sin(lat1)*Math.cos(delta)+Math.cos(lat1)*Math.sin(delta)*Math.cos(bearing));const lon2=lon1+Math.atan2(Math.sin(bearing)*Math.sin(delta)*Math.cos(lat1),Math.cos(delta)-Math.sin(lat1)*Math.sin(lat2));return{{latitude:lat2*180/Math.PI,longitude:lon2*180/Math.PI}}}}
if(data.azimuth!==null){{const origin=xy(data.station.latitude,data.station.longitude),left=destination(data.azimuth-data.azimuthTolerance,1200),centre=destination(data.azimuth,1200),right=destination(data.azimuth+data.azimuthTolerance,1200);const l=xy(left.latitude,left.longitude),c=xy(centre.latitude,centre.longitude),r=xy(right.latitude,right.longitude);el('path',{{d:`M${{origin[0]}} ${{origin[1]}} L${{l[0]}} ${{l[1]}} Q${{c[0]}} ${{c[1]}} ${{r[0]}} ${{r[1]}} Z`,class:'sector'}},sector)}}
function color(v){{const s=[[37,99,235],[6,182,212],[253,224,71],[220,38,38]],q=Math.max(0,Math.min(.999,v))*3,i=Math.floor(q),a=q-i,x=s[i],y=s[Math.min(i+1,3)];return`rgb(${{x.map((n,j)=>Math.round(n*(1-a)+y[j]*a)).join(',')}})`}}
function rows(p){{if(!p)return'<tr><td colspan="2">Geen route gevonden</td></tr>';return`<tr><td>Tegenstationgebied</td><td>${{p.lat.toFixed(4)}}°, ${{p.lon.toFixed(4)}}°</td></tr><tr><td>Scatterpunt</td><td>${{p.scatterLat.toFixed(4)}}°, ${{p.scatterLon.toFixed(4)}}°</td></tr><tr><td>Station A az/el</td><td>${{p.az1.toFixed(2)}}° / ${{p.el1.toFixed(2)}}°</td></tr><tr><td>Afstand A</td><td>${{p.distance1.toFixed(1)}} km</td></tr><tr><td>Aspectfout A</td><td>${{p.error1.toFixed(2)}}°</td></tr><tr><td>Tegenstation az/el</td><td>${{p.az2.toFixed(2)}}° / ${{p.el2.toFixed(2)}}°</td></tr><tr><td>Afstand tegenstation</td><td>${{p.distance2.toFixed(1)}} km</td></tr><tr><td>Aspectfout tegenstation</td><td>${{p.error2.toFixed(2)}}°</td></tr>`}}
const best=data.points[0],nodes=[];
data.points.forEach(p=>{{const q=xy(p.lat,p.lon),circle=el('circle',{{cx:q[0],cy:q[1],r:3.3,class:'reachable',fill:color(p.score),'fill-opacity':(.3+.6*p.score),'data-score':p.score}},points);circle.addEventListener('click',()=>{{document.getElementById('selection-help').textContent=`Geometry match ${{(p.score*100).toFixed(1)}}%`;document.getElementById('selected-table').innerHTML=rows(p)}});nodes.push(circle)}});
if(best&&data.skedScore!==null&&data.skedScore>=.7){{const a=xy(data.station.latitude,data.station.longitude),s=xy(best.scatterLat,best.scatterLon),b=xy(best.lat,best.lon);el('polyline',{{points:`${{a[0]}},${{a[1]}} ${{s[0]}},${{s[1]}}`,class:'path-a'}},route);el('polyline',{{points:`${{s[0]}},${{s[1]}} ${{b[0]}},${{b[1]}}`,class:'path-b'}},route);txt(s[0],s[1]+9,'★','best-scatter',markers);el('circle',{{cx:b[0],cy:b[1],r:8,class:'best-endpoint'}},markers)}}
const stationXY=xy(data.station.latitude,data.station.longitude);el('circle',{{cx:stationXY[0],cy:stationXY[1],r:9,class:'station'}},markers);txt(stationXY[0]+12,stationXY[1]-10,`A: ${{data.locator}}`,'label',labels,'start');
document.getElementById('best-table').innerHTML=best&&data.skedScore!==null&&data.skedScore>=.5?`<tr><td>Absolute sked-score</td><td>${{data.skedScore.toFixed(6)}}</td></tr>`+rows(best):'<tr><td colspan="2">Geen geloofwaardige route na vaste sked-controle (score &lt; 0,50). Geen antenneadvies.</td></tr>';
document.getElementById('model-table').innerHTML=`<tr><td>Azimutsector</td><td>${{data.azimuth===null?'alle richtingen':data.azimuth.toFixed(1)+'° ± '+data.azimuthTolerance.toFixed(1)+'°'}}</td></tr><tr><td>Hoogte</td><td>${{data.heightKm.toFixed(1)}} km</td></tr><tr><td>Raster</td><td>${{data.gridStepKm.toFixed(1)}} km</td></tr><tr><td>Min. elevatie</td><td>${{data.minElevationDeg.toFixed(1)}}°</td></tr><tr><td>Grenskaart</td><td>${{data.boundarySource}}</td></tr>`;
const slider=document.getElementById('score-filter'),scoreValue=document.getElementById('score-value'),counts=document.getElementById('counts');function filter(){{const threshold=Number(slider.value)/100;let shown=0;nodes.forEach(n=>{{const visible=Number(n.dataset.score)>=threshold;n.style.display=visible?'':'none';if(visible)shown++}});scoreValue.textContent=`${{slider.value}}%`;counts.textContent=`${{shown}} bereikbare grondcellen; ${{data.acceptedScatterCount}} scatterpunten gebruikt voor bistatische reverse search.`}}slider.addEventListener('input',filter);filter();
</script></body></html>"""
