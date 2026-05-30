from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import requests


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

OUT_GRIB = DATA_DIR / "latest_haines.grib2"
OUT_META = DATA_DIR / "metadata.json"


CYCLE = "00"
FORECAST_HOUR = 15
RESOLUTION = "0p25"


def get_valid_time_iso(date_yyyymmdd):
    base = datetime.strptime(date_yyyymmdd + CYCLE, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    valid = base + timedelta(hours=FORECAST_HOUR)
    return valid.isoformat()


def build_nomads_url(date_yyyymmdd):
    file_name = f"gfs.t{CYCLE}z.pgrb2.{RESOLUTION}.f{FORECAST_HOUR:03d}"

    base_url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"

    params = {
        "dir": f"/gfs.{date_yyyymmdd}/{CYCLE}/atmos",
        "file": file_name,

        # Variables necesarias para Haines
        "var_TMP": "on",
        "var_RH": "on",

        # Niveles necesarios para Haines bajo, medio y alto
        "lev_950_mb": "on",
        "lev_850_mb": "on",
        "lev_700_mb": "on",
        "lev_500_mb": "on",

        # Recorte aproximado Comunitat Valenciana
        "subregion": "",
        "leftlon": "-2.0",
        "rightlon": "1.0",
        "toplat": "41.0",
        "bottomlat": "37.5",
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base_url}?{query}", file_name


def is_grib(content):
    """
    Comprueba si la respuesta empieza como un archivo GRIB.
    """
    return content[:4] == b"GRIB"


def try_download_for_date(date_yyyymmdd):
    url, file_name = build_nomads_url(date_yyyymmdd)

    print("Intentando descarga:")
    print(url)

    headers = {
        "User-Agent": "MetVlc-Haines-GFS/1.0"
    }

    response = requests.get(url, headers=headers, timeout=180)

    print("Status:", response.status_code)
    print("Content-Type:", response.headers.get("content-type"))
    print("Tamaño:", len(response.content), "bytes")

    if response.status_code != 200:
        return False, url, file_name, f"HTTP {response.status_code}"

    # Si NOMADS devuelve HTML de error, normalmente no empieza por GRIB.
    if not is_grib(response.content):
        sample = response.content[:800].decode("utf-8", errors="replace")
        print("La respuesta no parece GRIB:")
        print(sample)
        return False, url, file_name, "La respuesta no empieza por GRIB"

    # Aunque sea pequeño, si empieza por GRIB lo aceptamos.
    OUT_GRIB.write_bytes(response.content)

    metadata = {
        "source": "NOAA NOMADS GFS 0.25",
        "model": "GFS",
        "resolution": "0.25",
        "cycle_date": date_yyyymmdd,
        "cycle": CYCLE,
        "forecast_hour": FORECAST_HOUR,
        "cycle_utc": f"{date_yyyymmdd} {CYCLE} UTC",
        "forecast_label": f"+{FORECAST_HOUR} h",
        "valid_utc": get_valid_time_iso(date_yyyymmdd),
        "file": file_name,
        "url": url,
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "note": "GFS 00 UTC +15 h. Producto orientado a la situación de tarde."
    }

    OUT_META.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("GRIB guardado correctamente.")
    print("Archivo:", OUT_GRIB)
    print("Metadata:", OUT_META)

    return True, url, file_name, "OK"


def main():
    now = datetime.now(timezone.utc)

    candidate_dates = [
        now.strftime("%Y%m%d"),
        (now - timedelta(days=1)).strftime("%Y%m%d"),
    ]

    errors = []

    for date_yyyymmdd in candidate_dates:
        ok, url, file_name, message = try_download_for_date(date_yyyymmdd)

        if ok:
            print("Descarga correcta")
            return

        errors.append({
            "date": date_yyyymmdd,
            "url": url,
            "file": file_name,
            "error": message,
        })

    raise RuntimeError(
        "No se ha podido descargar GFS 00 UTC +15 h. Errores: "
        + json.dumps(errors, indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
