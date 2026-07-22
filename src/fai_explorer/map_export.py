"""Zelfstandige SVG-kaart voor een Dual Station-resultaat."""

from __future__ import annotations

import json
from pathlib import Path

from .dual_station import CandidateResult, DualSearchResult


def write_scatter_map(
    result: DualSearchResult,
    locator_1: str,
    locator_2: str,
    output_path: str | Path,
) -> Path:
    """Schrijf het volledige scatterraster als zelfstandig HTML/SVG-bestand.

    Alle gegevens, opmaak en programmatuur staan in het HTML-bestand. Er zijn
    geen kaartserver, externe scripts, kaarttegels of internetverbinding nodig.
    """

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    bounds = _result_bounds(result)
    boundary_source, land_polygons = _load_land_polygons(bounds)
    payload = {
        "locator1": locator_1.upper(),
        "locator2": locator_2.upper(),
        "station1": {
            "latitude": result.station_1.latitude_deg,
            "longitude": result.station_1.longitude_deg,
        },
        "station2": {
            "latitude": result.station_2.latitude_deg,
            "longitude": result.station_2.longitude_deg,
        },
        "modelDate": result.model_date.isoformat(),
        "modelVersion": result.model_version,
        "visibleCount": result.visible_candidate_count,
        "acceptedCount": result.accepted_candidate_count,
        "gridStepKm": result.config.grid_step_km,
        "minElevationDeg": result.config.min_elevation_deg,
        "scatterAngleSigmaDeg": result.config.scatter_angle_sigma_deg,
        "maxScatterAngleDeg": result.config.max_scatter_angle_deg,
        "boundarySource": boundary_source,
        "landPolygons": land_polygons,
        "candidates": [_candidate_payload(candidate) for candidate in result.candidates],
    }
    data_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    path.write_text(_html_document(data_json), encoding="utf-8")
    return path


def _result_bounds(result: DualSearchResult) -> tuple[float, float, float, float]:
    """Geef kaartgrenzen als ``min_lat, max_lat, min_lon, max_lon``."""

    latitudes = [result.station_1.latitude_deg, result.station_2.latitude_deg]
    longitudes = [result.station_1.longitude_deg, result.station_2.longitude_deg]
    latitudes.extend(candidate.latitude_deg for candidate in result.candidates)
    longitudes.extend(candidate.longitude_deg for candidate in result.candidates)
    min_lat, max_lat = min(latitudes), max(latitudes)
    min_lon, max_lon = min(longitudes), max(longitudes)
    lat_pad = max((max_lat - min_lat) * 0.06, 0.25)
    lon_pad = max((max_lon - min_lon) * 0.06, 0.25)
    return min_lat - lat_pad, max_lat + lat_pad, min_lon - lon_pad, max_lon + lon_pad


def _load_land_polygons(
    bounds: tuple[float, float, float, float],
) -> tuple[str, list[dict[str, object]]]:
    """Lees alleen Natural Earth-polygonen die het kaartvenster raken."""

    resource = Path(__file__).with_name("data") / "country_boundaries.json"
    dataset = json.loads(resource.read_text(encoding="utf-8"))
    min_lat, max_lat, min_lon, max_lon = bounds
    selected: list[dict[str, object]] = []
    for country in dataset["countries"]:
        for ring in country["polygons"]:
            ring_lons = [coordinate[0] for coordinate in ring]
            ring_lats = [coordinate[1] for coordinate in ring]
            if (
                max(ring_lons) >= min_lon
                and min(ring_lons) <= max_lon
                and max(ring_lats) >= min_lat
                and min(ring_lats) <= max_lat
            ):
                selected.append({"name": country["name"], "ring": ring})
    return str(dataset["source"]), selected


def _candidate_payload(candidate: CandidateResult) -> dict[str, float]:
    return {
        "lat": candidate.latitude_deg,
        "lon": candidate.longitude_deg,
        "height": candidate.height_km,
        "score": candidate.score_total,
        "aspectScore": candidate.score_aspect,
        "elevationScore": candidate.score_elevation,
        "scatterAngleScore": candidate.score_scatter_angle,
        "bistaticError": candidate.bistatic_aspect_error_deg,
        "scatterAngle": candidate.scatter_angle_deg,
        "az1": candidate.azimuth_1_deg,
        "el1": candidate.elevation_1_deg,
        "distance1": candidate.distance_1_km,
        "error1": candidate.aspect_error_1_deg,
        "az2": candidate.azimuth_2_deg,
        "el2": candidate.elevation_2_deg,
        "distance2": candidate.distance_2_km,
        "error2": candidate.aspect_error_2_deg,
    }


def _html_document(data_json: str) -> str:
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FAI-scattergebied</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, Helvetica, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #e8edf2; color: #172033; }}
    header {{ padding: 14px 20px; background: #172033; color: white; }}
    header h1 {{ margin: 0; font-size: 20px; }}
    header p {{ margin: 5px 0 0; font-size: 13px; color: #cbd5e1; }}
    main {{ display: grid; grid-template-columns: minmax(620px, 1fr) 330px;
      gap: 12px; padding: 12px; min-height: calc(100vh - 75px); }}
    .map-card, .panel {{ background: white; border: 1px solid #cbd5e1;
      border-radius: 7px; box-shadow: 0 1px 4px rgba(15,23,42,.12); }}
    .map-card {{ min-width: 0; padding: 8px; display: flex; align-items: center; }}
    svg {{ width: 100%; height: auto; max-height: calc(100vh - 100px); background: #dceff7; }}
    .panel {{ padding: 15px; overflow: auto; }}
    .panel h2 {{ font-size: 16px; margin: 0 0 8px; }}
    .panel h3 {{ font-size: 14px; margin: 17px 0 6px; border-bottom: 1px solid #d7dee7;
      padding-bottom: 4px; }}
    .panel p {{ font-size: 12px; line-height: 1.4; margin: 5px 0; }}
    .panel table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .panel td {{ padding: 4px 3px; border-bottom: 1px solid #e5e7eb; }}
    .panel td:first-child {{ font-weight: 600; }}
    input[type=range] {{ width: 100%; }}
    .legend {{ height: 13px; border-radius: 3px; margin: 5px 0;
      background: linear-gradient(90deg,#2563eb,#06b6d4,#fde047,#dc2626); }}
    .muted {{ color: #64748b; }}
    .grid-line {{ stroke: #cbd5e1; stroke-width: 1; }}
    .grid-label {{ fill: #475569; font-size: 12px; }}
    .maidenhead-label {{ fill: #64748b; font-size: 10px; font-weight: 700;
      opacity: .58; pointer-events: none; }}
    .border {{ fill: #dceff7; stroke: #334155; stroke-width: 1.4; }}
    .land {{ fill: #e5e7eb; stroke: #94a3b8; stroke-width: .8;
      vector-effect: non-scaling-stroke; }}
    .path-1 {{ stroke: #15803d; stroke-width: 2.5; stroke-dasharray: 7 4; }}
    .path-2 {{ stroke: #7e22ce; stroke-width: 2.5; stroke-dasharray: 7 4; }}
    .direct-path {{ stroke: #475569; stroke-width: 1.4; stroke-dasharray: 2 5; }}
    .station {{ stroke: white; stroke-width: 2; }}
    .station-label {{ font-size: 14px; font-weight: 700; paint-order: stroke;
      stroke: white; stroke-width: 4; stroke-linejoin: round; }}
    .scatter-point {{ cursor: pointer; stroke: none; }}
    .scatter-point:hover {{ stroke: #111827; stroke-width: 2; r: 5; }}
    .best {{ fill: #111827; font-size: 28px; font-weight: 700; paint-order: stroke;
      stroke: white; stroke-width: 4; text-anchor: middle; cursor: pointer; }}
    .north {{ fill: #172033; font-size: 14px; font-weight: 700; text-anchor: middle; }}
    @media (max-width: 900px) {{
      main {{ grid-template-columns: 1fr; }}
      .map-card {{ min-width: 0; }}
      svg {{ max-height: none; }}
    }}
    @media print {{
      body {{ background: white; }} header {{ color: black; background: white; padding-left: 12px; }}
      header p {{ color: #334155; }} main {{ display: block; padding: 0; }}
      .map-card, .panel {{ box-shadow: none; border: 0; break-inside: avoid; }}
      .panel {{ margin-top: 8px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1 id="title">FAI Geometry Explorer</h1>
    <p id="subtitle"></p>
  </header>
  <main>
    <section class="map-card">
      <svg id="map" viewBox="0 0 1000 700" role="img" aria-label="FAI-scattergebied">
        <defs><clipPath id="plot-clip"><rect x="65" y="35" width="870" height="600"/></clipPath></defs>
        <rect class="border" x="65" y="35" width="870" height="600"/>
        <g id="land" clip-path="url(#plot-clip)"></g><g id="grid"></g>
        <g id="paths"></g><g id="scatter"></g>
        <g id="stations"></g><g id="labels"></g>
        <g transform="translate(905 77)">
          <path d="M0 22 L0 -22 M0 -22 L-7 -9 M0 -22 L7 -9" stroke="#172033" stroke-width="2" fill="none"/>
          <text class="north" x="0" y="-29">N</text>
        </g>
      </svg>
    </section>
    <aside class="panel">
      <h2>Scattergebied</h2>
      <p id="counts"></p>
      <label for="score-filter"><strong>Minimale absolute geometry match:</strong>
        <span id="score-value">70%</span></label>
      <input id="score-filter" type="range" min="0" max="100" value="70" step="1">
      <div class="legend"></div>
      <p class="muted">Het scattergebied gebruikt standaard een absolute geometry match van minimaal 70%.</p>

      <h3>Beste geometrische rasterpunt</h3>
      <table id="best-table"></table>

      <h3>Geselecteerd rasterpunt</h3>
      <p class="muted" id="selection-help">Klik op een gekleurd punt voor details.</p>
      <table id="selected-table"></table>

      <h3>Modelinstellingen</h3>
      <table id="model-table"></table>
      <p class="muted">Lokale equirectangulaire weergave. De numerieke azimut en elevatie zijn
        leidend voor de antennerichting; de kaart is bedoeld voor ruimtelijk overzicht.</p>
    </aside>
  </main>
  <script>
    const data = {data_json};
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.getElementById('map');
    const land = document.getElementById('land');
    const grid = document.getElementById('grid');
    const paths = document.getElementById('paths');
    const scatter = document.getElementById('scatter');
    const stations = document.getElementById('stations');
    const labels = document.getElementById('labels');
    const plot = {{left:65, top:35, width:870, height:600}};
    const credibleScore = 0.50;

    document.getElementById('title').textContent =
      `FAI-scattergebied ${{data.locator1}} ↔ ${{data.locator2}}`;
    document.getElementById('subtitle').textContent =
      `${{data.modelVersion}} · modeldatum ${{data.modelDate}} · zelfstandig lokaal kaartbestand`;

    const locations = [data.station1, data.station2,
      ...data.candidates.map(c => ({{latitude:c.lat, longitude:c.lon}}))];
    let minLat = Math.min(...locations.map(p => p.latitude));
    let maxLat = Math.max(...locations.map(p => p.latitude));
    let minLon = Math.min(...locations.map(p => p.longitude));
    let maxLon = Math.max(...locations.map(p => p.longitude));
    const latPad = Math.max((maxLat-minLat)*.06, .25);
    const lonPad = Math.max((maxLon-minLon)*.06, .25);
    minLat -= latPad; maxLat += latPad; minLon -= lonPad; maxLon += lonPad;
    const midLat = (minLat + maxLat) / 2;
    const lonFactor = Math.cos(midLat * Math.PI / 180);
    const projectedWidth = (maxLon-minLon) * lonFactor;
    const projectedHeight = maxLat-minLat;
    const scale = Math.min(plot.width/projectedWidth, plot.height/projectedHeight);
    const usedWidth = projectedWidth*scale, usedHeight = projectedHeight*scale;
    const offsetX = plot.left + (plot.width-usedWidth)/2;
    const offsetY = plot.top + (plot.height-usedHeight)/2;
    function xy(lat, lon) {{ return [
      offsetX + (lon-minLon)*lonFactor*scale,
      offsetY + (maxLat-lat)*scale
    ]; }}
    function element(name, attributes, parent) {{
      const node = document.createElementNS(NS, name);
      Object.entries(attributes).forEach(([key,value]) => node.setAttribute(key, value));
      (parent || svg).appendChild(node); return node;
    }}
    function text(x, y, value, className, parent, anchor='middle') {{
      const node = element('text', {{x,y,class:className,'text-anchor':anchor}}, parent);
      node.textContent = value; return node;
    }}
    function maidenhead4(lat,lon) {{
      const shiftedLon=Math.min(Math.max(lon+180,0),359.999999);
      const shiftedLat=Math.min(Math.max(lat+90,0),179.999999);
      const fieldLon=Math.floor(shiftedLon/20),fieldLat=Math.floor(shiftedLat/10);
      const squareLon=Math.floor((shiftedLon-fieldLon*20)/2);
      const squareLat=Math.floor(shiftedLat-fieldLat*10);
      return String.fromCharCode(65+fieldLon)+String.fromCharCode(65+fieldLat)+squareLon+squareLat;
    }}
    data.landPolygons.forEach(polygon => {{
      const commands=polygon.ring.map((coordinate,index) => {{
        const point=xy(coordinate[1],coordinate[0]);
        return `${{index===0?'M':'L'}}${{point[0].toFixed(1)}} ${{point[1].toFixed(1)}}`;
      }}).join(' ')+' Z';
      const shape=element('path',{{d:commands,class:'land'}},land);
      const tooltip=element('title',{{}},shape); tooltip.textContent=polygon.name;
    }});
    const latStep = 1, lonStep = 2;
    for (let lat=Math.ceil(minLat); lat<=maxLat; lat+=latStep) {{
      const [,y] = xy(lat,minLon);
      element('line', {{x1:offsetX,y1:y,x2:offsetX+usedWidth,y2:y,class:'grid-line'}}, grid);
      text(offsetX-8,y+4,`${{lat.toFixed(0)}}°`,'grid-label',grid,'end');
    }}
    for (let lon=Math.ceil(minLon/2)*2; lon<=maxLon; lon+=lonStep) {{
      const [x] = xy(minLat,lon);
      element('line', {{x1:x,y1:offsetY,x2:x,y2:offsetY+usedHeight,class:'grid-line'}}, grid);
      text(x,offsetY+usedHeight+18,`${{lon.toFixed(0)}}°`,'grid-label',grid);
    }}
    for (let lat=Math.floor(minLat); lat<maxLat; lat+=1) {{
      for (let lon=Math.floor(minLon/2)*2; lon<maxLon; lon+=2) {{
        const centreLat=lat+.5,centreLon=lon+1;
        if(centreLat>=minLat&&centreLat<=maxLat&&centreLon>=minLon&&centreLon<=maxLon){{
          const p=xy(centreLat,centreLon);
          text(p[0],p[1]+4,maidenhead4(centreLat,centreLon),'maidenhead-label',grid);
        }}
      }}
    }}

    function scoreColor(value) {{
      const stops = [[37,99,235],[6,182,212],[253,224,71],[220,38,38]];
      const scaled = Math.max(0,Math.min(.999,value))*3;
      const index = Math.floor(scaled), amount = scaled-index;
      const a=stops[index], b=stops[Math.min(index+1,3)];
      return `rgb(${{a.map((v,i)=>Math.round(v*(1-amount)+b[i]*amount)).join(',')}})`;
    }}
    function line(from, to, className) {{
      const a=xy(from.latitude,from.longitude), b=xy(to.lat,to.lon);
      element('line', {{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:className}}, paths);
    }}
    function tableRows(candidate) {{
      if (!candidate) return '<tr><td colspan="2">Geen kandidaat gevonden</td></tr>';
      return `
        <tr><td>Geometry-match</td><td>${{candidate.score.toFixed(6)}}</td></tr>
        <tr><td>Positie</td><td>${{candidate.lat.toFixed(4)}}°, ${{candidate.lon.toFixed(4)}}°</td></tr>
        <tr><td>Hoogte</td><td>${{candidate.height.toFixed(1)}} km</td></tr>
        <tr><td>Station 1 az/el</td><td>${{candidate.az1.toFixed(2)}}° / ${{candidate.el1.toFixed(2)}}°</td></tr>
        <tr><td>Afstand 1</td><td>${{candidate.distance1.toFixed(1)}} km</td></tr>
        <tr><td>Bistatische aspectfout</td><td>${{candidate.bistaticError.toFixed(2)}}°</td></tr>
        <tr><td>Richtingsverandering</td><td>${{candidate.scatterAngle.toFixed(2)}}°</td></tr>
        <tr><td>Afbuigingsscore</td><td>${{candidate.scatterAngleScore.toFixed(4)}}</td></tr>
        <tr><td>Station 2 az/el</td><td>${{candidate.az2.toFixed(2)}}° / ${{candidate.el2.toFixed(2)}}°</td></tr>
        <tr><td>Afstand 2</td><td>${{candidate.distance2.toFixed(1)}} km</td></tr>`;
    }}

    const pointNodes=[];
    data.candidates.forEach((candidate,index) => {{
      const [x,y]=xy(candidate.lat,candidate.lon);
      const circle=element('circle', {{cx:x,cy:y,r:3.2,class:'scatter-point',
        fill:scoreColor(candidate.score),'fill-opacity':(.28+.62*candidate.score).toFixed(2),
        'data-score':candidate.score}}, scatter);
      circle.addEventListener('click', () => {{
        document.getElementById('selection-help').textContent =
          `Geometry match ${{(candidate.score*100).toFixed(1)}}%`;
        document.getElementById('selected-table').innerHTML=tableRows(candidate);
      }});
      pointNodes.push(circle);
    }});

    const best=data.candidates[0];
    const station1xy=xy(data.station1.latitude,data.station1.longitude);
    const station2xy=xy(data.station2.latitude,data.station2.longitude);
    element('line',{{x1:station1xy[0],y1:station1xy[1],x2:station2xy[0],y2:station2xy[1],class:'direct-path'}},paths);
    if (best) {{
      line(data.station1,best,'path-1'); line(data.station2,best,'path-2');
      const [bx,by]=xy(best.lat,best.lon);
      const star=text(bx,by+9,'★','best',labels);
      star.addEventListener('click',()=>{{
        document.getElementById('selection-help').textContent=`Beste rasterpunt · geometry-match ${{(best.score*100).toFixed(1)}}%`;
        document.getElementById('selected-table').innerHTML=tableRows(best);
      }});
    }}
    function stationMarker(station,label,color,dy) {{
      const [x,y]=xy(station.latitude,station.longitude);
      element('circle',{{cx:x,cy:y,r:8,fill:color,class:'station'}},stations);
      text(x+11,y+dy,label,'station-label',labels,'start');
    }}
    stationMarker(data.station1,`1: ${{data.locator1}}`,'#15803d',-10);
    stationMarker(data.station2,`2: ${{data.locator2}}`,'#7e22ce',19);

    document.getElementById('best-table').innerHTML=best ?
      (best.score < credibleScore ? '<tr><td colspan="2"><strong>Lage geometry-match – alleen onderzoeksindicatie.</strong></td></tr>' : '') + tableRows(best) :
      '<tr><td colspan="2">Geen kandidaat gevonden.</td></tr>';
    document.getElementById('model-table').innerHTML=`
      <tr><td>Model</td><td>${{data.modelVersion}}</td></tr>
      <tr><td>Datum</td><td>${{data.modelDate}}</td></tr>
      <tr><td>Raster</td><td>${{data.gridStepKm.toFixed(1)}} km</td></tr>
      <tr><td>Min. elevatie</td><td>${{data.minElevationDeg.toFixed(1)}}°</td></tr>
      <tr><td>Afbuigingsstraf</td><td>${{data.scatterAngleSigmaDeg===null?'uitgeschakeld':data.scatterAngleSigmaDeg.toFixed(1)+'°'}}</td></tr>
      <tr><td>Max. afbuiging</td><td>${{data.maxScatterAngleDeg.toFixed(1)}}°</td></tr>`;
    document.getElementById('model-table').insertAdjacentHTML('beforeend',
      `<tr><td>Grenskaart</td><td>${{data.boundarySource}}</td></tr>`);
    const counts=document.getElementById('counts');
    const slider=document.getElementById('score-filter');
    const scoreValue=document.getElementById('score-value');
    function filterPoints() {{
      const threshold=Number(slider.value)/100; let shown=0;
      pointNodes.forEach(node=>{{
        const visible=Number(node.dataset.score)>=threshold;
        node.style.display=visible?'':'none'; if(visible) shown++;
      }});
      scoreValue.textContent=`${{slider.value}}%`;
      counts.textContent=`${{shown}} van ${{data.acceptedCount}} scatterpunten zichtbaar; `+
        `${{data.visibleCount}} rasterpunten waren bereikbaar vanaf beide stations.`;
    }}
    slider.addEventListener('input',filterPoints); filterPoints();
  </script>
</body>
</html>
"""
