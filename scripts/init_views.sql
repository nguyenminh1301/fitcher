-- Set trip_file and zones_file session variables to local paths before loading.
CREATE OR REPLACE VIEW trips AS
SELECT *
FROM read_parquet(getvariable('trip_file'))
WHERE hvfhs_license_num = 'HV0003';

CREATE OR REPLACE VIEW zones AS
SELECT *
FROM read_csv(
    getvariable('zones_file'),
    header = true,
    columns = {
        'LocationID': 'INTEGER',
        'Borough': 'VARCHAR',
        'Zone': 'VARCHAR',
        'service_zone': 'VARCHAR'
    }
);
