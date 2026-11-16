PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stations (
    station_key TEXT PRIMARY KEY,
    station_name TEXT,
    latitude REAL,
    longitude REAL,
    capacity INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS station_aliases (
    source TEXT NOT NULL,
    source_station_id TEXT NOT NULL,
    station_key TEXT NOT NULL REFERENCES stations(station_key),
    source_station_name TEXT,
    match_method TEXT NOT NULL,
    PRIMARY KEY (source, source_station_id)
);

CREATE TABLE IF NOT EXISTS trips (
    trip_key TEXT PRIMARY KEY,
    source_month TEXT NOT NULL,
    source_trip_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL CHECK(duration_seconds >= 0),
    start_station_key TEXT REFERENCES stations(station_key),
    end_station_key TEXT REFERENCES stations(station_key),
    start_station_name TEXT,
    end_station_name TEXT,
    rider_type TEXT NOT NULL CHECK(rider_type IN ('member','casual','unknown')),
    rideable_type TEXT,
    source_schema TEXT NOT NULL,
    UNIQUE(source_month, source_trip_id)
);
CREATE INDEX IF NOT EXISTS idx_trips_started_at ON trips(started_at);
CREATE INDEX IF NOT EXISTS idx_trips_start_station ON trips(start_station_key);
CREATE INDEX IF NOT EXISTS idx_trips_end_station ON trips(end_station_key);

CREATE TABLE IF NOT EXISTS daily_weather (
    date TEXT PRIMARY KEY,
    temperature_mean_c REAL,
    precipitation_mm REAL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS station_snapshots (
    captured_at TEXT NOT NULL,
    station_key TEXT NOT NULL REFERENCES stations(station_key),
    gbfs_station_id TEXT NOT NULL,
    bikes_available INTEGER,
    docks_available INTEGER,
    capacity INTEGER,
    is_installed INTEGER,
    is_renting INTEGER,
    is_returning INTEGER,
    PRIMARY KEY(captured_at, gbfs_station_id)
);

CREATE TABLE IF NOT EXISTS rejected_records (
    source_month TEXT NOT NULL,
    source_trip_id TEXT,
    reason TEXT NOT NULL,
    record_json TEXT NOT NULL
);

