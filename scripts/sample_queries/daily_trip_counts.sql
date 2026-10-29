SELECT CAST(pickup_datetime AS DATE) AS pickup_date, count(*) AS trip_count
FROM trips
GROUP BY pickup_date
ORDER BY pickup_date;
