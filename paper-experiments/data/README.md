# Data

No data is included; the datasets belong to data owners in the PISTIS project, who grant access.

- Flight operations, one year: a spreadsheet of 121,580 flights and 188 columns, used as three samples of 5,000 rows.
- Baggage handling, two months: four semicolon-delimited CSV files (arrival, departure, transfer, breakdown).
- Gridded weather, four months: 854 GeoTIFF rasters (122 days, 7 variables, 325 x 529 cells), 5,000 fixed cells per day.

File and column names are read from `data/sources.toml` (see `sources.example.toml`, paths relative to `PISTIS_DATA_DIR`).
The example uses `flight/file_01.xlsx`, `baggage/file_01.csv` to `file_04.csv` and `weather/<variable>_<YYYYMMDD>.tiff`.
