from pathlib import Path
from datetime import datetime, timezone
import json
import numpy as np
import xarray as xr


GRIB_FILE = Path("data/latest_haines.grib2")
META_FILE = Path("data/metadata.json")

OUT_GEOJSON = Path("docs/haines.geojson")
OUT_META = Path("docs/haines_metadata.json")

OUT_GEOJSON.parent.mkdir(exist_ok=True)


def score(values, low_limit, mid_limit):
    """
    Devuelve puntuación Haines 1, 2 o 3.
    1 = bajo
    2 = medio
    3 = alto
    """
    return xr.where(
        values <= low_limit,
        1,
        xr.where(values <= mid_limit, 2, 3)
    )


def get_level(ds, var_name, level):
    """
    Extrae una variable en un nivel isobárico concreto.
    """
    if "isobaricInhPa" not in ds[var_name].coords:
        raise ValueError(f"La variable {var_name} no tiene coordenada isobaricInhPa")

    return ds[var_name].sel(isobaricInhPa=level)


def dewpoint_from_temp_rh(temp_c, rh_percent):
    """
    Calcula punto de rocío en ºC a partir de temperatura en ºC
    y humedad relativa en % usando la aproximación de Magnus.
    """
    rh = rh_percent.clip(min=1, max=100)

    a = 17.625
    b = 243.04

    gamma = np.log(rh / 100.0) + (a * temp_c) / (b + temp_c)
    td = (b * gamma) / (a - gamma)

    return td


def main():
    if not GRIB_FILE.exists():
        raise FileNotFoundError(f"No existe {GRIB_FILE}")

    ds = xr.open_dataset(
        GRIB_FILE,
        engine="cfgrib",
        backend_kwargs={
            "filter_by_keys": {"typeOfLevel": "isobaricInhPa"},
            "indexpath": ""
        }
    )

    print(ds)

    if "t" not in ds:
        raise ValueError("No encuentro la variable de temperatura 't' en el GRIB")

    if "r" not in ds:
        raise ValueError("No encuentro la variable de humedad relativa 'r' en el GRIB")

    # Temperaturas en ºC
    t950 = get_level(ds, "t", 950) - 273.15
    t850 = get_level(ds, "t", 850) - 273.15
    t700 = get_level(ds, "t", 700) - 273.15
    t500 = get_level(ds, "t", 500) - 273.15

    # Humedad relativa en %
    rh850 = get_level(ds, "r", 850)
    rh700 = get_level(ds, "r", 700)

    # Punto de rocío estimado en ºC a partir de T + HR
    td850 = dewpoint_from_temp_rh(t850, rh850)
    td700 = dewpoint_from_temp_rh(t700, rh700)

    # ==========================
    # HAINES BAJO
    # 950-850 hPa + sequedad 850
    # ==========================
    estabilidad_baja = t950 - t850
    sequedad_baja = t850 - td850

    haines_bajo = (
        score(estabilidad_baja, 3, 7) +
        score(sequedad_baja, 5, 9)
    )

    # ==========================
    # HAINES MEDIO
    # 850-700 hPa + sequedad 850
    # ==========================
    estabilidad_media = t850 - t700
    sequedad_media = t850 - td850

    haines_medio = (
        score(estabilidad_media, 5, 10) +
        score(sequedad_media, 5, 12)
    )

    # ==========================
    # HAINES ALTO
    # 700-500 hPa + sequedad 700
    # ==========================
    estabilidad_alta = t700 - t500
    sequedad_alta = t700 - td700

    haines_alto = (
        score(estabilidad_alta, 17, 21) +
        score(sequedad_alta, 14, 20)
    )

    lats = ds.latitude.values
    lons = ds.longitude.values

    features = []

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            lon_value = float(lon)

            if lon_value > 180:
                lon_value -= 360

            hb = int(haines_bajo.values[i, j])
            hm = int(haines_medio.values[i, j])
            ha = int(haines_alto.values[i, j])

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon_value, float(lat)]
                },
                "properties": {
                    "haines_bajo": hb,
                    "haines_medio": hm,
                    "haines_alto": ha,

                    "estabilidad_baja": round(float(estabilidad_baja.values[i, j]), 1),
                    "sequedad_baja": round(float(sequedad_baja.values[i, j]), 1),

                    "estabilidad_media": round(float(estabilidad_media.values[i, j]), 1),
                    "sequedad_media": round(float(sequedad_media.values[i, j]), 1),

                    "estabilidad_alta": round(float(estabilidad_alta.values[i, j]), 1),
                    "sequedad_alta": round(float(sequedad_alta.values[i, j]), 1),

                    "t850": round(float(t850.values[i, j]), 1),
                    "t700": round(float(t700.values[i, j]), 1),
                    "t500": round(float(t500.values[i, j]), 1),
                    "rh850": round(float(rh850.values[i, j]), 1),
                    "rh700": round(float(rh700.values[i, j]), 1),
                    "td850_estimado": round(float(td850.values[i, j]), 1),
                    "td700_estimado": round(float(td700.values[i, j]), 1),
                }
            }

            features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    OUT_GEOJSON.write_text(
        json.dumps(geojson, ensure_ascii=False),
        encoding="utf-8"
    )

    metadata = {}

    if META_FILE.exists():
        metadata = json.loads(META_FILE.read_text(encoding="utf-8"))

    metadata.update({
        "product": "Índice de Haines",
        "description": "Cálculo experimental del Índice de Haines bajo, medio y alto a partir de GFS 0.25",
        "geojson": str(OUT_GEOJSON),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dewpoint_method": "Punto de rocío estimado a partir de temperatura y humedad relativa mediante fórmula de Magnus",
        "variants": {
            "bajo": "950-850 hPa + sequedad en 850 hPa",
            "medio": "850-700 hPa + sequedad en 850 hPa",
            "alto": "700-500 hPa + sequedad en 700 hPa"
        }
    })

    OUT_META.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"GeoJSON creado: {OUT_GEOJSON}")
    print(f"Metadata creada: {OUT_META}")


if __name__ == "__main__":
    main()
