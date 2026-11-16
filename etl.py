#!/usr/bin/env python3
"""Small, idempotent Divvy + weather ETL using Python's standard library."""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import re
import sqlite3
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
SNAPSHOTS = ROOT / "snapshots"
LOGS = ROOT / "logs"
DB = ROOT / "divvy.db"
MONTHS = ("2019-12", "2021-01", "2021-02")
TRIP_BASE = "https://divvy-tripdata.s3.amazonaws.com/"
DISCOVERY = "https://gbfs.divvybikes.com/gbfs/gbfs.json"
WEATHER_BASE = "https://archive-api.open-meteo.com/v1/archive"
MAX_DURATION_SECONDS = 24 * 60 * 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("divvy_etl")


def fetch(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "divvy-assignment-etl/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)


def month_bounds(month: str) -> tuple[str, str]:
    start = dt.date.fromisoformat(month + "-01")
    next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return start.isoformat(), (next_month - dt.timedelta(days=1)).isoformat()


def get_field(row: dict[str, str], *names: str) -> str | None:
    indexed = {re.sub(r"[^a-z0-9]", "", key.lower()): value for key, value in row.items() if key}
    for name in names:
        value = indexed.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if value not in (None, ""):
            return value.strip()
    return None


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    value = value.strip().replace("Z", "+00:00")
    for form in (None, "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            parsed = dt.datetime.fromisoformat(value) if form is None else dt.datetime.strptime(value, form)
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            continue
    return None


def station_key(name: str | None, source: str, source_id: str | None) -> tuple[str | None, str]:
    if name and name.strip():
        normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return "name:" + normalized, "normalized_name"
    if source_id:
        return f"id:{source}:{source_id}", "source_scoped_id"
    return None, "unmatched_missing_id_and_name"


def ensure_station(conn: sqlite3.Connection, key: str, name: str | None, now: str,
                   lat: float | None = None, lon: float | None = None,
                   capacity: int | None = None) -> None:
    conn.execute("""INSERT INTO stations(station_key,station_name,latitude,longitude,capacity,first_seen_at,last_seen_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(station_key) DO UPDATE SET
        station_name=COALESCE(excluded.station_name,stations.station_name),
        latitude=COALESCE(excluded.latitude,stations.latitude), longitude=COALESCE(excluded.longitude,stations.longitude),
        capacity=COALESCE(excluded.capacity,stations.capacity), last_seen_at=excluded.last_seen_at""",
        (key, name, lat, lon, capacity, now, now))


def trip_archives() -> dict[str, tuple[str, str]]:
    return {
        "2019-12": ("Divvy_Trips_2019_Q4.zip", "Divvy_Trips_2019_Q4.csv"),
        "2021-01": ("202101-divvy-tripdata.zip", "202101-divvy-tripdata.csv"),
        "2021-02": ("202102-divvy-tripdata.zip", "202102-divvy-tripdata.csv"),
    }


def extract_trips() -> dict[str, tuple[zipfile.ZipFile, object]]:
    streams = {}
    for month, (archive_name, csv_name) in trip_archives().items():
        archive_path = RAW / archive_name
        if not archive_path.exists():
            fetch(TRIP_BASE + archive_name, archive_path)
        zf = zipfile.ZipFile(archive_path)
        streams[month] = (zf, zf.open(csv_name))
    return streams


def capture_gbfs() -> tuple[str, dict, dict]:
    discovery_path = RAW / "gbfs_discovery.json"
    fetch(DISCOVERY, discovery_path)
    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    feeds = discovery.get("data", {}).get("en", {}).get("feeds", [])
    urls = {item["name"]: item["url"] for item in feeds}
    missing = {"station_information", "station_status"} - urls.keys()
    if missing:
        raise RuntimeError(f"GBFS discovery is missing feeds: {sorted(missing)}")
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    stamp = dt.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    bodies = {}
    for name in ("station_information", "station_status"):
        path = SNAPSHOTS / f"{name}_{stamp}.json"
        fetch(urls[name], path)
        bodies[name] = json.loads(path.read_text(encoding="utf-8"))
    (SNAPSHOTS / f"capture_{stamp}.json").write_text(json.dumps({
        "captured_at": captured_at, "discovery_url": DISCOVERY,
        "feeds": {key: urls[key] for key in ("station_information", "station_status")},
    }, indent=2), encoding="utf-8")
    return captured_at, bodies["station_information"], bodies["station_status"]


def capture_weather(months: tuple[str, ...]) -> None:
    for month in months:
        start, end = month_bounds(month)
        params = urlencode({"latitude": 41.88, "longitude": -87.63, "start_date": start,
                            "end_date": end, "daily": "temperature_2m_mean,precipitation_sum",
                            "timezone": "America/Chicago"})
        path = RAW / f"weather_{month}.json"
        if not path.exists():
            fetch(WEATHER_BASE + "?" + params, path)


def load_weather(conn: sqlite3.Connection, months: tuple[str, ...]) -> int:
    count = 0
    for month in months:
        payload = json.loads((RAW / f"weather_{month}.json").read_text(encoding="utf-8"))
        daily = payload.get("daily", {})
        dates = daily.get("time", [])
        temps = daily.get("temperature_2m_mean", [])
        rain = daily.get("precipitation_sum", [])
        for day, temp, precip in zip(dates, temps, rain):
            conn.execute("""INSERT INTO daily_weather(date,temperature_mean_c,precipitation_mm,source)
                VALUES(?,?,?,'Open-Meteo archive') ON CONFLICT(date) DO UPDATE SET
                temperature_mean_c=excluded.temperature_mean_c,precipitation_mm=excluded.precipitation_mm,
                source=excluded.source""", (day, temp, precip))
            count += 1
    return count


def load_stations_and_status(conn: sqlite3.Connection, captured_at: str, info: dict, status: dict,
                             feed_issues: list[dict]) -> int:
    info_rows = {str(row.get("station_id")): row for row in info.get("data", {}).get("stations", [])}
    count = 0
    for item in status.get("data", {}).get("stations", []):
        station_id = str(item.get("station_id", ""))
        meta = info_rows.get(station_id, {})
        name = meta.get("name")
        bikes = item.get("num_bikes_available")
        capacity = meta.get("capacity")
        if isinstance(bikes, int) and isinstance(capacity, int) and capacity > 0 and bikes > capacity:
            feed_issues.append({"captured_at":captured_at,"station_id":station_id,"station_name":name or "",
                                "issue":"bikes_exceed_capacity","observed":bikes,"expected_max":capacity})
        lat, lon = meta.get("lat"), meta.get("lon")
        if lat is not None and lon is not None and not (41.2 <= lat <= 42.4 and -88.4 <= lon <= -87.2):
            feed_issues.append({"captured_at":captured_at,"station_id":station_id,"station_name":name or "",
                                "issue":"coordinates_outside_chicago_area","observed":f"{lat},{lon}","expected_max":"Chicago metro bounds"})
        key, method = station_key(name, "gbfs", station_id)
        ensure_station(conn, key, name, captured_at, lat, lon, capacity)
        conn.execute("""INSERT INTO station_aliases(source,source_station_id,station_key,source_station_name,match_method)
            VALUES('gbfs',?,?,?,?) ON CONFLICT(source,source_station_id) DO UPDATE SET
            station_key=excluded.station_key,source_station_name=excluded.source_station_name,match_method=excluded.match_method""",
            (station_id, key, name, method))
        conn.execute("""INSERT OR REPLACE INTO station_snapshots
            (captured_at,station_key,gbfs_station_id,bikes_available,docks_available,capacity,is_installed,is_renting,is_returning)
            VALUES(?,?,?,?,?,?,?,?,?)""", (captured_at, key, station_id, bikes,
            item.get("num_docks_available"), capacity, item.get("is_installed"),
            item.get("is_renting"), item.get("is_returning")))
        count += 1
    return count


def process_trips(conn: sqlite3.Connection, streams: dict, issues: list[dict]) -> tuple[int, int]:
    loaded = skipped = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for month, (zf, binary) in streams.items():
        month_loaded = month_skipped = month_filtered = 0
        import io
        text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        columns = {re.sub(r"[^a-z0-9]", "", c.lower()) for c in (reader.fieldnames or [])}
        old_schema = "tripid" in columns
        schema_label = "legacy_quarterly" if old_schema else "monthly_modern"
        for row_number, row in enumerate(reader, 2):
            trip_id = get_field(row, "trip_id", "ride_id")
            start = parse_time(get_field(row, "start_time", "started_at"))
            end = parse_time(get_field(row, "end_time", "ended_at"))
            reason = None
            if not trip_id:
                reason = "missing_trip_id"
            elif not start or not end:
                reason = "invalid_or_missing_timestamp"
            elif start.strftime("%Y-%m") != month:
                # The 2019 source is a quarter file; only December belongs to this run.
                month_filtered += 1
                continue
            else:
                seconds = (end - start).total_seconds()
                if seconds < 0:
                    reason = "negative_duration"
                elif seconds == 0:
                    reason = "zero_duration"
                elif seconds > MAX_DURATION_SECONDS:
                    reason = "duration_over_24_hours"
            if reason:
                issues.append({"source_month": month, "source_trip_id": trip_id or "", "reason": reason,
                               "record_json": json.dumps(row, ensure_ascii=False)})
                skipped += 1
                month_skipped += 1
                continue
            duration = (end - start).total_seconds()
            start_id = get_field(row, "from_station_id", "start_station_id")
            end_id = get_field(row, "to_station_id", "end_station_id")
            start_name = get_field(row, "from_station_name", "start_station_name")
            end_name = get_field(row, "to_station_name", "end_station_name")
            source = f"trips:{month}"
            start_key, start_method = station_key(start_name, source,
                start_id)
            end_key, end_method = station_key(end_name, source,
                end_id)
            for key, name, station_id, method in ((start_key,start_name,start_id,start_method),(end_key,end_name,end_id,end_method)):
                if key is not None:
                    ensure_station(conn, key, name, now)
                if station_id and key is not None:
                    conn.execute("""INSERT INTO station_aliases(source,source_station_id,station_key,source_station_name,match_method)
                        VALUES(?,?,?,?,?) ON CONFLICT(source,source_station_id) DO NOTHING""",
                        (source, str(station_id), key, name, method))
            rider = (get_field(row, "member_casual", "usertype") or "unknown").strip().lower()
            rider = "member" if rider in ("member", "subscriber") else ("casual" if rider in ("casual", "customer") else "unknown")
            rideable = get_field(row, "rideable_type", "bike_type")
            source_schema = schema_label
            conn.execute("""INSERT OR IGNORE INTO trips
                (trip_key,source_month,source_trip_id,started_at,ended_at,duration_seconds,start_station_key,end_station_key,
                 start_station_name,end_station_name,rider_type,rideable_type,source_schema)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (f"{month}:{trip_id}", month, str(trip_id), start.isoformat(" "), end.isoformat(" "),
                duration, start_key, end_key, start_name, end_name, rider, rideable, source_schema))
            loaded += conn.execute("SELECT changes()").fetchone()[0]
            month_loaded += conn.execute("SELECT changes()").fetchone()[0]
        text.detach()
        zf.close()
        LOG.info("Normalized %s (%s): inserted=%d rejected=%d out-of-month=%d",
                 month, schema_label, month_loaded, month_skipped, month_filtered)
    return loaded, skipped


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    with (ROOT / "schema.sql").open(encoding="utf-8") as schema:
        conn = sqlite3.connect(DB)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema.read())
        captured_at, info, status = capture_gbfs()
        capture_weather(MONTHS)
        streams = extract_trips()
        issues: list[dict] = []
        feed_issues: list[dict] = []
        with conn:
            # This table is the latest run's validation output, so reruns do not duplicate rejects.
            conn.execute("DELETE FROM rejected_records")
            trip_count, skipped = process_trips(conn, streams, issues)
            weather_count = load_weather(conn, MONTHS)
            live_count = load_stations_and_status(conn, captured_at, info, status, feed_issues)
            for issue in issues:
                conn.execute("INSERT INTO rejected_records(source_month,source_trip_id,reason,record_json) VALUES(?,?,?,?)",
                             (issue["source_month"], issue["source_trip_id"], issue["reason"], issue["record_json"]))
        report_path = LOGS / "quality_report.csv"
        with report_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=("source_month","source_trip_id","reason","record_json"))
            writer.writeheader(); writer.writerows(issues)
        feed_report_path = LOGS / "feed_quality_report.csv"
        with feed_report_path.open("w", newline="", encoding="utf-8") as f:
            fields = ("captured_at","station_id","station_name","issue","observed","expected_max")
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader(); writer.writerows(feed_issues)
        orphan_count = conn.execute("PRAGMA foreign_key_check").fetchall()
        if orphan_count:
            raise RuntimeError(f"Foreign key validation failed: {orphan_count[:10]}")
        unnamed_trips = conn.execute("SELECT COUNT(*) FROM trips WHERE start_station_name IS NULL OR end_station_name IS NULL").fetchone()[0]
        unmatched_endpoints = conn.execute("SELECT SUM(start_station_key IS NULL)+SUM(end_station_key IS NULL) FROM trips").fetchone()[0]
        LOG.info("Validation summary: foreign-key violations=0, trips with a missing endpoint name=%d, unmatched endpoints=%d, live-feed issues=%d",
                 unnamed_trips, unmatched_endpoints, len(feed_issues))
        LOG.info("Run complete: valid trips inserted=%d, records skipped/rejected=%d, weather rows=%d, live station rows=%d; db=%s",
                 trip_count, skipped, weather_count, live_count, DB)
        LOG.info("Validation details: %s; feed details: %s", report_path, feed_report_path)
        conn.close()


if __name__ == "__main__":
    main()

