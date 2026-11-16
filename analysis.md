# Chicago Divvy analysis

All figures below come from `queries.sql` run against `divvy.db` produced by `etl.py`. The selected trip periods are Dec 2019, Jan 2021, and Feb 2021; they contain 301,304 accepted trips. The live comparison uses snapshot `snapshots/capture_20261116T142322+0530.json`, captured at 2026-11-16 14:23:22 +05:30. The 2019 source archive covers the full fourth quarter, but only December starts are included.

## 1. Same-station trips by rider class

| Month | Rider | Trips | Classifiable endpoint pairs | Same station | Share of classifiable |
|---|---:|---:|---:|---:|---:|
| 2019-12 | Casual | 16,365 | 16,365 | 1,982 | 12.11% |
| 2019-12 | Member | 138,647 | 138,647 | 1,709 | 1.23% |
| 2021-01 | Casual | 18,090 | 14,675 | 1,707 | 11.63% |
| 2021-01 | Member | 78,701 | 68,818 | 2,955 | 4.29% |
| 2021-02 | Casual | 10,072 | 8,592 | 1,186 | 13.80% |
| 2021-02 | Member | 39,429 | 34,379 | 1,957 | 5.69% |

Casual riders have a higher same-station share in all three periods, by 10.88, 7.34, and 8.11 percentage points respectively. Of 301,304 accepted trips, 281,476 (93.42%) have both station endpoints classifiable. Among those, 11,496 are same-station rides (4.08%); relative to all accepted trips this is a conservative 3.82% because 19,828 trips have an unclassifiable endpoint pair. A plausible explanation is that casual trips more often include recreational loops; this selected winter sample also contains different customer mixes and operating conditions, so the gap alone does not establish why riders returned to the origin.

## 2. Most common station pairs

Top pairs, excluding same-station trips:

| Start | End | Trips |
|---|---|---:|
| Ellis Ave & 60th St | Ellis Ave & 55th St | 340 |
| Ellis Ave & 55th St | Ellis Ave & 60th St | 284 |
| Lake Shore Dr & Monroe St | Streeter Dr & Grand Ave | 258 |
| Ellis Ave & 60th St | University Ave & 57th St | 194 |
| Canal St & Adams St | Michigan Ave & Washington St | 185 |
| Columbus Dr & Randolph St | State St & Randolph St | 185 |
| University Ave & 57th St | Kimbark Ave & 53rd St | 175 |
| University Ave & 57th St | Lake Park Ave & 56th St | 166 |
| Wabash Ave & Roosevelt Rd | Michigan Ave & 18th St | 162 |
| Canal St & Madison St | Michigan Ave & Washington St | 161 |

The symmetric Ellis Ave & 60th/55th trips lead both directions, while the lakefront route is also prominent. Among trips with classifiable station endpoints, 95.92% end at a different station, so the core service in this sample is point-to-point transport; same-station rides are a smaller but meaningful recreational or return-to-origin segment.

## 3. Time-of-week patterns

Weekdays show commute-like peaks: 17:00 is the busiest hour overall with 31,348 trips, and 08:00 has 22,578. Every weekday's busiest hour is 17:00 in the selected sample: Monday 5,671 trips, Tuesday 5,160, Wednesday 5,052, Thursday 5,541, and Friday 5,051 (counts summed across the three selected months). Weekday 08:00 is also prominent, e.g. Monday 4,521 and Thursday 4,268.

Weekend trips look more leisure-oriented: Saturday 14:00 has 4,157 trips averaging 20.3 minutes; Sunday 14:00 has 3,317 averaging 21.0 minutes. For comparison, Tuesday 08:00 has 4,007 trips averaging 11.1 minutes. Average trip duration is 18.0 minutes Saturday and 17.7 Sunday, versus 13.1–14.3 minutes on weekdays. This is consistent with longer daytime leisure rides alongside shorter weekday commuting, although the data does not identify rider purpose directly.

## 4. Precipitation and volume

I compare average trip counts on rainy versus dry calendar days because it gives an operationally interpretable relative difference and uses all 90 selected days without fitting a small-sample correlation. A rainy day has precipitation above 0 mm.

| Day type | Days | Average trips/day |
|---|---:|---:|
| Dry | 47 | 3,926.74 |
| Rainy | 43 | 2,715.05 |

Rainy days have **30.9% fewer trips per day** than dry days: `(2715.05 - 3926.74) / 3926.74`. This is an association, not a causal estimate. Month, temperature, and weekday mix can explain part of the difference. I would test those factors with a daily regression or matched comparison controlling for month, weekday, and temperature, then estimate the precipitation coefficient and uncertainty.

## 5. Live station stress and historical imbalance

The captured status feed contains 2,079 stations. The feed has seven rows where `num_bikes_available` exceeds the station metadata `capacity`; they are retained and listed in `logs/feed_quality_report.csv`. The raw threshold flags include tiny public racks and contradictory rows, so for crew triage I focus on installed, rentable stations with capacity of at least 10 and available bikes no greater than capacity. In that operational set, 168 stations are below 10% or above 90% bike occupancy: 151 low-bike and 17 near-full. Occupancy is `num_bikes_available / capacity`.

Exact normalized station-name matching yields 605 historical station keys that also occur in the live feed out of 673 distinct historical keys. That leaves 68 historical keys without a confident exact-name live match. In the 2021 trip data, 19,828 trips have a missing start or end station name (13,298 in January, 6,530 in February); 28,183 endpoint references across all selected periods have neither a name nor ID and remain null. These are not guessed into live identities.

Of the 168 operationally stressed live stations, 68 have historical trips in the selected months (55 low-bike and 13 near-full). Historical flow direction agrees with current status for 39 of 55 low-bike stations (historical net inflow is negative) and 3 of 13 near-full stations (net inflow is positive). Examples include LaSalle St & Adams St, empty now with historical net inflow -46, and Chicago Ave & Washington St, at 100% with net inflow +7. Direction does not always agree; 16 historically active low-bike and 10 near-full stations show the opposite or neutral pattern. The four-to-five-year gap, the winter-only sample, renamed/expanded stations, and changing demand patterns all limit the comparison.

## 6. Five-station morning rebalancing rule

Use the latest status snapshot and keep installed, rentable stations with capacity >=10, bikes <= capacity, and at least one historical trip. Mark a station stressed below 10% or above 90%. Score it by distance beyond the nearest threshold in percentage points; break ties by historical flow direction (negative net inflow reinforces a low-bike priority; positive net inflow reinforces a near-full priority), then by absolute historical net flow. Send crews to the five highest scores. For an empty destination, bring bikes; for a near-full destination, remove bikes. Recheck status before dispatch because a snapshot is only a point in time.

The query ranks these five stations first; all are empty at capture time and have historical net outflow, so live shortage and past direction reinforce each other:

| Station | Bikes / capacity | Historical net inflow | Historical trips |
|---|---:|---:|---:|
| Franklin St & Monroe St | 0 / 48 | -181 | 3,759 |
| Sheridan Rd & Irving Park Rd | 0 / 31 | -84 | 2,594 |
| Sheffield Ave & Wrightwood Ave | 0 / 36 | -62 | 1,214 |
| LaSalle St & Adams St | 0 / 15 | -46 | 1,120 |
| Lake Park Ave & 35th St | 0 / 19 | -16 | 230 |

This rule combines immediate need with evidence of recurring directional pressure, while avoiding anomalous feed rows and stations with no historical evidence. The ranking query in `queries.sql` returns the five stations and their current capacity and historical net flow from the exact database snapshot.

## Data-quality investigation

1. **Long trips:** 80 December 2019, 37 January 2021, and 117 February 2021 records exceed 24 hours. They are rejected, with the original CSV row in `rejected_records` and `logs/quality_report.csv`.
2. **Nonpositive durations:** January 2021 has two negative and four zero-duration trips; February 2021 has four zero-duration trips. Durations are recomputed from timestamps, and these eight zero plus two negative records are reported and excluded.
3. **Station-name gaps and identifier drift:** 19,828 trips across Jan/Feb 2021 lack at least one endpoint name, and 28,183 endpoint references lack both a usable name and ID. Legacy 2019 station IDs and 2021 IDs are not assumed to refer to the same station; a known ID without a name uses a source-scoped ID, while a fully unidentified endpoint remains null. Name-present endpoints join only on normalized exact name. This keeps trips queryable without falsely asserting a match.
4. **Live-feed capacity conflict:** seven captured station statuses report more available bikes than the station metadata capacity. The snapshot is preserved, each discrepancy is listed in `feed_quality_report.csv`, and those rows do not enter the recommended rebalancing ranking.

The 2019 input is also a quarterly file: 548,962 October/November rows are outside the chosen December month and are filtered by date, not mislabeled as bad records. Run logs report the out-of-month count separately.

