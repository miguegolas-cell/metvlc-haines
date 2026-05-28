from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import json
import sys

# Zona aproximada Comunitat Valenciana y alrededores
BBOX = {
    "leftlon": -2.5,
    "rightlon": 1.5,
    "toplat": 41.0,
    "bottomlat": 37.5,
}

# Niveles necesarios para Índice de Haines
LEVELS = [
    "lev_950_mb",
    "lev_850_mb",
    "lev_700_mb",
    "lev_500_mb",
]

# Variables necesarias
VARIABLES = [
    "var_TMP",   # Temperatura
    "var_DPT",   # Punto de rocío
    "var_RH",    # Humedad relativa, por seguridad
]

OUT_DIR = Path("data")
OUT_DIR.mkdir(exist_ok=True)

GRIB_OUT = OUT_DIR / "latest_haines.grib2"
META_OUT = OUT_DIR / "metadata.json"


def build_url(date_str, cycle, fhr):
    file_name = f"gfs.t{cycle}z.pgrb2.0p25.f{fhr:03d}"

    params = {
        "file": file_name,
        "subregion": "",
        "leftlon": BBOX["leftlon"],
        "rightlon": BBOX["rightlon"],
        "toplat": BBOX["toplat"],
        "bottomlat": BBOX["bottomlat"],
        "dir": f"/gfs.{date_str}/{cycle}/atmos",
    }

    for level in LEVELS:
        params[level] = "on"

    for var in VARIABLES:
        params[var] = "on"

    return "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?" + urlencode(params)


def download(url):
    req = Request(url, headers={"User-Agent": "MetVlc-Haines-Downloader/1.0"})

    with urlopen(req, timeout=90) as response:
        data = response.read()

    if b"<html" in data[:300].lower():
        raise RuntimeError("NOMADS devolvió HTML, no GRIB.")

    if len(data) < 1000:
        raise RuntimeError(f"Archivo demasiado pequeño: {len(data)} bytes.")

    return data


def candidate_cycles():
    now = datetime.now(timezone.utc)
    candidates = []

    for hours_back in range(0, 48):
        t = now - timedelta(hours=hours_back)
        date_str = t.strftime("%Y%m%d")

        for cycle in ["18", "12", "06", "00"]:
            cycle_dt = datetime(
                t.year,
                t.month,
                t.day,
                int(cycle),
                tzinfo=timezone.utc
            )

            # Evitamos ciclos demasiado recientes porque pueden no estar completos
            if cycle_dt <= now - timedelta(hours=4):
                candidates.append((date_str, cycle))

    seen = set()
    clean = []

    for item in candidates:
        if item not in seen:
            clean.append(item)
            seen.add(item)

    return clean


def main():
    forecast_hours = [0, 3, 6]
    last_error = None

    for date_str, cycle in candidate_cycles():
        for fhr in forecast_hours:
            url = build_url(date_str, cycle, fhr)

            print(f"Probando: {date_str} ciclo {cycle} f{fhr:03d}")
            print(url)

            try:
                data = download(url)
                GRIB_OUT.write_bytes(data)

                metadata = {
                    "source": "NOAA NOMADS GFS 0.25",
                    "date": date_str,
                    "cycle_utc": cycle,
                    "forecast_hour": fhr,
                    "file": str(GRIB_OUT),
                    "size_bytes": len(data),
                    "bbox": BBOX,
                    "levels": LEVELS,
                    "variables": VARIABLES,
                    "download_url": url,
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                }

                META_OUT.write_text(
                    json.dumps(metadata, indent=2),
                    encoding="utf-8"
                )

                print(f"Descarga correcta: {GRIB_OUT} ({len(data)} bytes)")
                print(f"Metadata: {META_OUT}")
                return

            except Exception as e:
                last_error = e
                print(f"Fallo: {e}")

    print("No se pudo descargar ningún GRIB válido.")
    print(f"Último error: {last_error}")
    sys.exit(1)


if __name__ == "__main__":
    main()
