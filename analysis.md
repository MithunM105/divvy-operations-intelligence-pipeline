# Divvy trip and station analysis

This report answers the six analysis questions in the assignment. The numbers come from the SQL in `queries.sql` and the selected data: December 2019, January 2021, and February 2021. There are **301,304 accepted trips**.

The live station results below use the snapshot captured on **November 16, 2026 at 14:23:22 +05:30**. A later ETL run captures a new snapshot, so the live-station query can show different results from this report.

## 1. Same-station trips by month and rider type

A same-station trip starts and ends at the same station. The percentages below use trips with both station endpoints classifiable.

| Month | Rider type | Classifiable trips | Same-station trips | Same-station share |
|---|---|---:|---:|---:|
| Dec 2019 | Casual | 16,365 | 1,982 | 12.11% |
| Dec 2019 | Member | 138,647 | 1,709 | 1.23% |
| Jan 2021 | Casual | 14,675 | 1,707 | 11.63% |
| Jan 2021 | Member | 68,818 | 2,955 | 4.29% |
| Feb 2021 | Casual | 8,592 | 1,186 | 13.80% |
| Feb 2021 | Member | 34,379 | 1,957 | 5.69% |

Casual riders have a higher same-station share in all three periods. Recreational rides that return to their starting point could help explain this, but the trip data does not record a rider's purpose, so this is an explanation to investigate rather than a proven cause.

Across all riders, 281,476 trips have both endpoints classifiable. Of those, 11,496 end at the starting station: **4.08% of classifiable trips**. Compared with all 301,304 accepted trips, that is **3.82%**. The difference in denominators matters because some trip endpoints cannot be identified.

## 2. Top station-to-station routes

These are the ten most common routes after excluding same-station trips.

| Start station | End station | Trips |
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

Most classifiable trips end at a different station from where they began. This suggests that point-to-point travel is the main use in this sample, while same-station trips make up a smaller but meaningful share.

## 3. Trip duration by hour and day of week

The query returns trip counts and average durations for each observed hour-and-weekday combination. These examples show two patterns:

- **Weekday commute-like activity:** 17:00 is the busiest hour overall, with 31,348 trips; 08:00 has 22,578. Each weekday's busiest hour is 17:00. Tuesday at 08:00 has 4,007 trips averaging 11.1 minutes.
- **Longer weekend afternoon rides:** Saturday at 14:00 has 4,157 trips averaging 20.3 minutes. Sunday at 14:00 has 3,317 trips averaging 21.0 minutes. Average trip duration is 18.0 minutes on Saturdays and 17.7 on Sundays, compared with 13.1–14.3 minutes on weekdays.

These patterns are consistent with weekday commuting and longer weekend rides. The records do not directly state why a person took a trip.

## 4. Rain and daily trip volume

A rainy day is a day with precipitation greater than zero millimeters. I compare average trips per calendar day because it is easy to interpret for operations and uses all 90 selected days.

| Day type | Days | Average trips per day |
|---|---:|---:|
| Dry | 47 | 3,926.74 |
| Rainy | 43 | 2,715.05 |

Rainy days had about **30.9% fewer trips per day** than dry days. This is a relationship in this sample, not proof that rain alone caused the drop. Temperature, month, and weekday mix could also affect volume. A next analysis could compare similar weekdays and temperatures or use a daily regression that controls for month, weekday, and temperature.

## 5. Live station stress and historical trip flows

For this comparison, a station is considered operational if it is installed, renting, has capacity of at least 10, and its reported bike count does not exceed capacity. A station is stressed if fewer than 10% of its docks' capacity are occupied by bikes, or more than 90% are occupied.

In the report's snapshot, **168 stations** met those criteria: 151 had low bike availability and 17 were near full. The feed had seven other rows where available bikes exceeded the station's listed capacity; they were reported as data conflicts and left out of the crew ranking.

The pipeline confidently matched 605 of 673 historical station keys to a live station by normalized exact name. It leaves 68 unmatched rather than guessing. Of the 168 stressed stations, 68 had historical trips in this sample: 55 low-bike stations and 13 near-full stations.

- For 39 of the 55 low-bike stations, historical net inflow was negative, meaning more trips departed than arrived.
- For 3 of the 13 near-full stations, historical net inflow was positive, meaning more trips arrived than departed.

For example, LaSalle St & Adams St was empty in the captured snapshot and had historical net inflow of -46. Chicago Ave & Washington St was full and had historical net inflow of +7.

The match is imperfect, as expected. The live snapshot and historical trips are years apart, the chosen trip months are winter months, and station names or service patterns can change.

## 6. A rule for choosing five stations tomorrow morning

The proposed rule is:

1. Keep installed, rentable stations with capacity of at least 10, valid bike counts, and historical trip evidence.
2. Flag stations below 10% bike occupancy or above 90%.
3. Rank them by how far they are beyond the nearest threshold. When two stations are equally stressed, prioritize one whose historical net flow points in the same direction as the current problem.
4. Recheck the live status before sending a crew.

For an empty station, bring bikes. For a near-full station, remove bikes. The five leading stations for the report's snapshot were:

| Station | Bikes / capacity | Historical net inflow | Historical trips |
|---|---:|---:|---:|
| Franklin St & Monroe St | 0 / 48 | -181 | 3,759 |
| Sheridan Rd & Irving Park Rd | 0 / 31 | -84 | 2,594 |
| Sheffield Ave & Wrightwood Ave | 0 / 36 | -62 | 1,214 |
| LaSalle St & Adams St | 0 / 15 | -46 | 1,120 |
| Lake Park Ave & 35th St | 0 / 19 | -16 | 230 |

All five were empty in the snapshot and had more historical departures than arrivals, so the live shortage and historical direction point the same way. This is a transparent triage rule, not a guarantee of future demand.

## Data quality issues found

The assignment asks for specific issues observed in the selected data. These are the main three and how the pipeline handles them.

1. **Invalid trip durations:** 80 December 2019, 37 January 2021, and 117 February 2021 records were longer than 24 hours. January also had two negative and four zero-duration records; February had four zero-duration records. The pipeline recomputes duration from timestamps, rejects these trips, and records the reason and original row.
2. **Missing station details and changing identifiers:** 19,828 January and February trips are missing at least one endpoint name. Across all selected months, 28,183 endpoint references have neither a usable name nor ID. The pipeline uses exact normalized names where possible, keeps IDs source-specific when no name is present, and leaves fully unknown endpoints unmatched.
3. **Contradictory live capacity:** seven station-status rows report more available bikes than the station metadata says the station can hold. The raw snapshot is preserved, each issue is reported, and these rows are excluded from the crew ranking.

The 2019 input is a quarterly archive. Its 548,962 October and November rows are filtered out because the selected period is December; they are out-of-period records, not rejected trips.


