CREATE SETTINGS PROFILE OR REPLACE `fitcher_agent__minimal` SETTINGS readonly = 2 CONST, max_execution_time = 30 MIN 1 MAX 120, max_result_rows = 10000 MIN 1 MAX 100000, max_memory_usage = 2000000000 MIN 1 MAX 4000000000
CREATE ROLE IF NOT EXISTS `fitcher_role__minimal__blue_viewer`
CREATE ROLE IF NOT EXISTS `fitcher_role__minimal__summary_reader`
CREATE ROLE IF NOT EXISTS `fitcher_role__minimal__viewer`
CREATE OR REPLACE VIEW `marts`.`fitcher_agg__minimal__summary_reader__widget_sales` DEFINER = CURRENT_USER SQL SECURITY DEFINER AS SELECT `sold_on`, `widget_name`, sum(sale_amount) AS `widget_revenue`, count() AS `row_count` FROM `marts`.`widget_sales` GROUP BY `sold_on`, `widget_name` HAVING count() >= 5
GRANT SELECT(`sale_amount`, `sale_ref`, `sold_on`, `widget_name`) ON `marts`.`widget_sales` TO `fitcher_role__minimal__blue_viewer`
GRANT SELECT ON `marts`.`fitcher_agg__minimal__summary_reader__widget_sales` TO `fitcher_role__minimal__summary_reader`
GRANT SELECT(`refund_ref`, `refund_total`, `refunded_on`, `sale_ref`) ON `marts`.`widget_refunds` TO `fitcher_role__minimal__viewer`
GRANT SELECT(`sale_amount`, `sale_ref`, `sold_on`, `widget_name`) ON `marts`.`widget_sales` TO `fitcher_role__minimal__viewer`
CREATE ROW POLICY OR REPLACE `fitcher_row__minimal__blue_viewer` ON `marts`.`widget_sales` USING (widget_name = 'Blue Widget') TO `fitcher_role__minimal__blue_viewer`
CREATE USER IF NOT EXISTS `fitcher_agent__minimal__viewer` IDENTIFIED WITH sha256_hash BY '84b70516fde428b50bb325644515ad7899008f6d066c1b15dba621f0d055bfc6'
GRANT `fitcher_role__minimal__viewer` TO `fitcher_agent__minimal__viewer`
ALTER USER `fitcher_agent__minimal__viewer` IDENTIFIED WITH sha256_hash BY '84b70516fde428b50bb325644515ad7899008f6d066c1b15dba621f0d055bfc6' DEFAULT ROLE `fitcher_role__minimal__viewer` SETTINGS PROFILE 'fitcher_agent__minimal'
CREATE USER IF NOT EXISTS `fitcher_agent__minimal__blue_viewer` IDENTIFIED WITH sha256_hash BY '1c572234262e3af2a7f01744a8424207b2cabc832cb6e666026c13834f40abd4'
GRANT `fitcher_role__minimal__blue_viewer` TO `fitcher_agent__minimal__blue_viewer`
ALTER USER `fitcher_agent__minimal__blue_viewer` IDENTIFIED WITH sha256_hash BY '1c572234262e3af2a7f01744a8424207b2cabc832cb6e666026c13834f40abd4' DEFAULT ROLE `fitcher_role__minimal__blue_viewer` SETTINGS PROFILE 'fitcher_agent__minimal'
CREATE USER IF NOT EXISTS `fitcher_agent__minimal__summary_reader` IDENTIFIED WITH sha256_hash BY '059b8cd8c3e61b43bc5850c80d002c6d316e9d6487be5f8f1ef40cc62debfda0'
GRANT `fitcher_role__minimal__summary_reader` TO `fitcher_agent__minimal__summary_reader`
ALTER USER `fitcher_agent__minimal__summary_reader` IDENTIFIED WITH sha256_hash BY '059b8cd8c3e61b43bc5850c80d002c6d316e9d6487be5f8f1ef40cc62debfda0' DEFAULT ROLE `fitcher_role__minimal__summary_reader` SETTINGS PROFILE 'fitcher_agent__minimal'
