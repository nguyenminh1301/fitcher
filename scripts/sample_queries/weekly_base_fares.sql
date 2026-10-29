-- Base fare excludes tolls, tips, taxes and fees; it is not net revenue.
SELECT CAST(date_trunc('week', pickup_datetime) AS DATE) AS week_start,
       count(*) AS trip_count,
       sum(CAST(base_passenger_fare AS DECIMAL(18, 2))) AS base_fare_total
FROM trips
GROUP BY week_start
ORDER BY week_start;
