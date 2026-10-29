WITH pickup_counts AS (
    SELECT PULocationID AS location_id, count(*) AS trip_count
    FROM trips
    GROUP BY PULocationID
)
SELECT t.location_id,
       coalesce(z.Borough, 'Unknown') AS borough,
       coalesce(z.Zone, 'Unknown') AS zone,
       t.trip_count
FROM pickup_counts AS t
LEFT JOIN zones AS z ON t.location_id = z.LocationID
ORDER BY trip_count DESC, location_id
LIMIT 10;
