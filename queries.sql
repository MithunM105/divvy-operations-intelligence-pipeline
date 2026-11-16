-- 1) Same-station share by selected month and rider class.
SELECT source_month, rider_type, COUNT(*) AS trips,
       SUM(start_station_key IS NOT NULL AND end_station_key IS NOT NULL) AS classifiable_station_pairs,
       SUM(start_station_key = end_station_key) AS same_station_trips,
       ROUND(100.0 * SUM(start_station_key = end_station_key) /
             NULLIF(SUM(start_station_key IS NOT NULL AND end_station_key IS NOT NULL),0), 2) AS same_station_pct
FROM trips GROUP BY source_month, rider_type ORDER BY source_month, rider_type;

-- Overall share of same-station trips.
SELECT COUNT(*) AS trips,
       SUM(start_station_key IS NOT NULL AND end_station_key IS NOT NULL) AS classifiable_station_pairs,
       SUM(start_station_key = end_station_key) AS same_station_trips,
       ROUND(100.0 * SUM(start_station_key = end_station_key) /
             NULLIF(SUM(start_station_key IS NOT NULL AND end_station_key IS NOT NULL),0), 2) AS same_station_pct_of_classifiable,
       ROUND(100.0 * SUM(start_station_key = end_station_key) / COUNT(*), 2) AS same_station_pct_of_all_trips
FROM trips;

-- 2) Top origin-destination pairs, excluding same-station journeys.
SELECT start_station_name, end_station_name, COUNT(*) AS trips
FROM trips WHERE start_station_key IS NOT NULL AND end_station_key IS NOT NULL
  AND start_station_key <> end_station_key
GROUP BY start_station_key, end_station_key, start_station_name, end_station_name
ORDER BY trips DESC LIMIT 10;

-- 3) Duration by hour and weekday (0=Sunday through 6=Saturday).
SELECT CAST(strftime('%H', started_at) AS INTEGER) AS hour,
       CAST(strftime('%w', started_at) AS INTEGER) AS weekday,
       COUNT(*) AS trips, ROUND(AVG(duration_seconds)/60.0, 2) AS avg_minutes
FROM trips GROUP BY hour, weekday ORDER BY weekday, hour;

-- 4) Compare rainy days (any measurable precipitation) with dry days.
WITH daily AS (
  SELECT date(started_at) AS day, COUNT(*) AS trips
  FROM trips GROUP BY date(started_at)
), labeled AS (
  SELECT CASE WHEN COALESCE(w.precipitation_mm,0) > 0 THEN 'rainy' ELSE 'dry' END AS weather,
         d.day, d.trips
  FROM daily d JOIN daily_weather w ON w.date=d.day
)
SELECT weather, COUNT(*) AS days, ROUND(AVG(trips),2) AS avg_trips_per_day,
       SUM(trips) AS total_trips
FROM labeled GROUP BY weather;

-- Historical balance: net inflow = trip arrivals minus departures.
WITH flows AS (
  SELECT station_key, SUM(inflow) AS inflow, SUM(outflow) AS outflow, SUM(inflow)+SUM(outflow) AS trip_volume
  FROM (
  SELECT end_station_key AS station_key, COUNT(*) AS inflow, 0 AS outflow FROM trips
    WHERE end_station_key IS NOT NULL GROUP BY end_station_key
    UNION ALL
  SELECT start_station_key, 0, COUNT(*) FROM trips
    WHERE start_station_key IS NOT NULL GROUP BY start_station_key
  ) GROUP BY station_key
)
SELECT station_key, inflow, outflow, inflow-outflow AS net_inflow
FROM flows ORDER BY ABS(inflow-outflow) DESC LIMIT 30;

-- 5) Current stress (<10% bikes available or >90% bikes available vs capacity)
-- With matched historical net flow, negative means more departures than arrivals.
WITH flows AS (
  SELECT station_key, SUM(inflow) AS inflow, SUM(outflow) AS outflow, SUM(inflow)+SUM(outflow) AS trip_volume
  FROM (
    SELECT end_station_key AS station_key, COUNT(*) AS inflow, 0 AS outflow FROM trips
      WHERE end_station_key IS NOT NULL GROUP BY end_station_key
    UNION ALL
    SELECT start_station_key, 0, COUNT(*) FROM trips
      WHERE start_station_key IS NOT NULL GROUP BY start_station_key
  ) GROUP BY station_key
)
SELECT s.station_name, ss.gbfs_station_id, ss.bikes_available, ss.docks_available, ss.capacity,
       ROUND(100.0*ss.bikes_available/NULLIF(ss.capacity,0),1) AS bike_occupancy_pct,
       COALESCE(f.inflow,0) AS historical_inflow, COALESCE(f.outflow,0) AS historical_outflow,
       COALESCE(f.inflow,0)-COALESCE(f.outflow,0) AS historical_net_inflow,
       CASE WHEN 100.0*ss.bikes_available/NULLIF(ss.capacity,0)<10 THEN 'low_bikes' ELSE 'near_full' END AS stress
FROM station_snapshots ss JOIN stations s USING(station_key)
LEFT JOIN flows f USING(station_key)
WHERE ss.captured_at=(SELECT MAX(captured_at) FROM station_snapshots)
  AND ss.capacity>=10 AND ss.bikes_available<=ss.capacity
  AND ss.is_installed=1 AND ss.is_renting=1
  AND (100.0*ss.bikes_available/ss.capacity<10 OR 100.0*ss.bikes_available/ss.capacity>90)
ORDER BY ABS(100.0*ss.bikes_available/ss.capacity-50) DESC;

-- 6) Candidate five crews: most severe live stress, with historical direction for context.
WITH flows AS (
  SELECT station_key, SUM(inflow) AS inflow, SUM(outflow) AS outflow, SUM(inflow)+SUM(outflow) AS trip_volume
  FROM (
  SELECT end_station_key AS station_key, COUNT(*) AS inflow, 0 AS outflow FROM trips
    WHERE end_station_key IS NOT NULL GROUP BY end_station_key
    UNION ALL
  SELECT start_station_key, 0, COUNT(*) FROM trips
    WHERE start_station_key IS NOT NULL GROUP BY start_station_key
  ) GROUP BY station_key
), stressed AS (
  SELECT s.station_name, ss.gbfs_station_id, ss.bikes_available, ss.capacity,
         100.0*ss.bikes_available/NULLIF(ss.capacity,0) AS occupancy_pct,
         COALESCE(f.inflow,0)-COALESCE(f.outflow,0) AS historical_net_inflow,
         COALESCE(f.trip_volume,0) AS historical_trip_volume,
         ss.is_installed, ss.is_renting
  FROM station_snapshots ss JOIN stations s USING(station_key)
  LEFT JOIN flows f USING(station_key)
  WHERE ss.captured_at=(SELECT MAX(captured_at) FROM station_snapshots)
    AND ss.capacity>=10 AND ss.bikes_available<=ss.capacity
    AND ss.is_installed=1 AND ss.is_renting=1 AND COALESCE(f.trip_volume,0)>0
    AND (100.0*ss.bikes_available/ss.capacity<10 OR 100.0*ss.bikes_available/ss.capacity>90)
)
SELECT *, ROUND(CASE WHEN occupancy_pct<10 THEN 10-occupancy_pct ELSE occupancy_pct-90 END,1) AS severity_points
FROM stressed
ORDER BY severity_points DESC,
         CASE WHEN occupancy_pct<10 AND historical_net_inflow<0 THEN 1
              WHEN occupancy_pct>90 AND historical_net_inflow>0 THEN 1 ELSE 0 END DESC,
         ABS(historical_net_inflow) DESC LIMIT 5;

-- Validation summary to explain concrete data quality findings.
SELECT source_month, reason, COUNT(*) AS records FROM rejected_records
GROUP BY source_month, reason ORDER BY source_month, reason;

