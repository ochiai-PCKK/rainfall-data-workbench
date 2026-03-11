SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_dir TEXT NOT NULL,
  time_start TEXT,
  time_end TEXT,
  crs_raw TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grids (
  dataset_id TEXT PRIMARY KEY,
  grid_crs TEXT,
  origin_x REAL NOT NULL,
  origin_y REAL NOT NULL,
  cell_width REAL NOT NULL,
  cell_height REAL NOT NULL,
  rows INTEGER NOT NULL,
  cols INTEGER NOT NULL,
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
);

CREATE TABLE IF NOT EXISTS cell_timeseries (
  dataset_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  row INTEGER NOT NULL,
  col INTEGER NOT NULL,
  x_center REAL NOT NULL,
  y_center REAL NOT NULL,
  rainfall_mm REAL,
  quality TEXT,
  PRIMARY KEY (dataset_id, observed_at, row, col),
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
);

CREATE TABLE IF NOT EXISTS polygons (
  polygon_id TEXT PRIMARY KEY,
  polygon_name TEXT NOT NULL,
  polygon_group TEXT,
  polygon_crs TEXT NOT NULL,
  minx REAL NOT NULL,
  miny REAL NOT NULL,
  maxx REAL NOT NULL,
  maxy REAL NOT NULL,
  geometry_wkt TEXT NOT NULL,
  file_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS polygon_cell_map (
  dataset_id TEXT NOT NULL,
  polygon_id TEXT NOT NULL,
  row INTEGER NOT NULL,
  col INTEGER NOT NULL,
  polygon_local_row INTEGER,
  polygon_local_col INTEGER,
  cell_area REAL,
  overlap_area REAL,
  overlap_ratio REAL,
  inside_flag INTEGER NOT NULL,
  selection_method TEXT NOT NULL,
  PRIMARY KEY (dataset_id, polygon_id, row, col),
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id),
  FOREIGN KEY (polygon_id) REFERENCES polygons(polygon_id)
);

CREATE INDEX IF NOT EXISTS idx_cell_timeseries_dataset_time
  ON cell_timeseries (dataset_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_cell_timeseries_dataset_cell
  ON cell_timeseries (dataset_id, row, col);

CREATE INDEX IF NOT EXISTS idx_polygon_cell_map_dataset_polygon
  ON polygon_cell_map (dataset_id, polygon_id);
"""
