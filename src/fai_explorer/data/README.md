# Ingebouwde kaartgegevens

`country_boundaries.json` is afgeleid van **Natural Earth Admin-0 Countries
1:50m, versie 5.1.1**. De polygonen zijn tot 0,025 graad vereenvoudigd en
bevatten alleen landcontouren en landsgrenzen die voor orientatie nodig zijn.

Natural Earth stelt alle raster- en vectordata beschikbaar in het publieke
domein: <https://www.naturalearthdata.com/about/terms-of-use/>.

De bronlaag kan opnieuw worden verwerkt met:

```console
python tools/build_country_boundaries.py \
  ne_50m_admin_0_countries.shp \
  src/fai_explorer/data/country_boundaries.json
```
