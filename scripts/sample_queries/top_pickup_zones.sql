SELECT t.PULocationID AS location_id,
       coalesce(z.Borough, 'Unknown') AS borough,
       coalesce(z.Zone, 'Unknown') AS zone,
       count(*) AS trip_count
FROM trips AS t
LEFT JOIN zones AS z ON t.PULocationID = z.LocationID
GROUP BY t.PULocationID, z.Borough, z.Zone
ORDER BY trip_count DESC, location_id
LIMIT 10;
