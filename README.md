# Chicago Divvy Intelligence Pipeline

An end-to-end, local ETL project that combines Divvy historical trips, Chicago weather, and a live GBFS station snapshot into a queryable SQLite database. The pipeline uses Python's standard library only and records raw GBFS responses before loading them.

## Selected data and capture

- Historical trip months: December 2019, January 2021, and February 2021. December 2019 comes from Divvy's quarterly legacy archive and is filtered by trip start date; the 2021 months are monthly CSV archives.
- Weather: Open-Meteo daily mean temperature and precipitation at 41.88, -87.63 for the same 90 calendar days.
- Live data: `station_information` and `station_status`, discovered from the GBFS discovery feed. Capture time and feed URLs are recorded in each `snapshots/capture_*.json` file. Raw feed bodies are retained beside the metadata.
- Sources: [Divvy system data](https://divvybikes.com/system-data), [GBFS discovery](https://gbfs.divvybikes.com/gbfs/gbfs.json), and [Open-Meteo historical archive](https://open-meteo.com/en/docs/historical-weather-api).

The [Divvy Data License Agreement](https://divvybikes.com/data-license-agreement) prohibits distributing the trip records as a stand-alone dataset. The public repository contains the pipeline, aggregate analysis, and the required GBFS snapshot; it does not commit the trip ZIPs, trip-level SQLite database, or row-level validation extracts. `etl.py` downloads the trip archives when run and builds those local outputs.

## Architecture

`etl.py` downloads source archives and weather JSON to `data/raw/`, captures timestamped GBFS JSON to `snapshots/`, normalizes trips into a common shape, validates records, and loads everything to `divvy.db`. `schema.sql` defines the SQLite tables, keys, constraints, and indexes. `queries.sql` contains the analytical SQL. `analysis.md` records measured results and the operational interpretation. Validation rows are written to `logs/quality_report.csv` and live-feed checks to `logs/feed_quality_report.csv`.

Station identity is reconciled using a normalized exact station name when one is present. Source-specific IDs are retained in `station_aliases`. If a historical trip has an ID but no station name, the pipeline creates a source-scoped station key rather than guessing that it matches a similarly numbered live ID. If both name and ID are absent, the trip endpoint stays null and is counted as unmatched instead of being grouped into a synthetic station. The analysis identifies the number of exact name matches and keeps unresolved stations visible.

## Setup and run

Requires Python 3.11 or newer and outbound HTTPS access to the public source endpoints. No third-party packages are needed; the delivered database was built with Python 3.13.9.

```powershell
cd chicago-divvy-pipeline
python etl.py
```

The script creates `divvy.db`, downloads any missing historical ZIPs and weather responses, and captures a new live snapshot on every run. Historical trips are idempotent by month and source trip ID; each run refreshes the validation reports. GBFS snapshots are intentionally append-only so each run preserves its own capture.

To inspect SQL results with Python:

```powershell
python -c "import sqlite3; c=sqlite3.connect('divvy.db'); print(c.execute('select source_month,count(*) from trips group by 1').fetchall())"
```

## Data modeling and assumptions

- The three months are intentionally discontinuous to cover the legacy-to-modern schema change.
- All trip durations are recomputed from start and end timestamps. Missing or invalid timestamps, nonpositive durations, negative durations, and durations over 24 hours are rejected with the raw row retained in the quality report.
- The quarterly 2019 file is filtered to December based on `start_time`; October and November rows are outside the selected period and are counted separately in the run log.
- Exact normalized station-name matching is intentionally conservative. It avoids fuzzy merges across similarly named stations; unmatched source IDs remain source-scoped.
- Daily weather is joined to trip start date in Chicago local time. A rainy day means precipitation greater than zero millimeters.
- A live station is considered for the rebalancing ranking only if it is installed, renting, has capacity of at least 10, and its reported bike count does not exceed reported capacity. This avoids ranking tiny racks or contradictory status rows above regular operating stations.

## Challenges and tool use

The 2019 archive is a quarterly file with `trip_id`, `start_time`, `from_station_id`, and `usertype`, while the 2021 files use `ride_id`, `started_at`, `start_station_id`, and `member_casual`. The normalizer resolves fields by canonicalized column names and uses values, rather than month-specific transformations. Some 2021 station names are blank; those trips stay queryable using source-scoped IDs but are not asserted to match current GBFS stations.

Codex helped draft the pipeline, schema, SQL, and report. On the first execution I caught a legacy-schema detection bug caused by checking the unnormalized header spelling; I corrected it to use the canonical field name and reran the pipeline. I also caught live status records where available bikes exceed the metadata capacity and added a feed-quality report plus an exclusion rule for rebalancing candidates.

## Production follow-ups

For production, schedule ingestion with retries and source checksums, store raw files in object storage, use a warehouse for larger history, version schema mappings, add freshness/volume alerts, preserve quality reports by run ID, and estimate expected station pressure by matching weekday and time of day instead of relying on a three-month aggregate.

