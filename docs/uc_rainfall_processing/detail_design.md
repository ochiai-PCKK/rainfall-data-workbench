# UC降雨処理 詳細設計

## 1. 目的

本書は、`requirements.md` および `design.md` を受けて、初期実装を進めるための詳細設計を定義する。

対象は以下とする。

- フェーズ1: 取り込み、時刻復元、空間判定、中間データ格納
- フェーズ2: 候補セル参照、セル選択、期間指定、最大イベント抽出、グラフ出力


## 2. 実装対象範囲

初期実装で実施するもの:

- UC-tools ダウンロードディレクトリまたは ZIP ファイルの解析
- `rain.dat` の読み取り
- JST 時刻列の復元
- 格子定義の抽出
- 流域ポリゴン読込
- `BBox -> ポリゴン内判定` による候補セル抽出
- SQLite への保存
- CLI による候補セル一覧表示
- `local_row/local_col` 指定によるセル選択
- 流域内全セルの合計時系列生成
- 流域内全セルの平均時系列生成
- 表示期間指定
- 同一格子定義を持つ複数 `dataset_id` の時系列結合
- 指定期間内の各指標最大イベント抽出
- PNG グラフ出力

初期実装で実施しないもの:

- 流域代表時系列生成
- `polygon_timeseries` テーブル
- Web UI
- 地図 GUI


## 3. ディレクトリ構成案

実装ファイルは `src` 配下で以下のように分割することを想定する。

```text
src/
  uc_rainfall/
    __init__.py
    cli.py
    db.py
    schema.py
    models.py
    ingest/
      __init__.py
      uc_loader.py
      rain_dat_parser.py
      time_resolver.py
      grid_builder.py
    spatial/
      __init__.py
      polygon_loader.py
      cell_locator.py
      cell_selector.py
    graph/
      __init__.py
      metrics.py
      event_detector.py
      chart_renderer.py
    services/
      __init__.py
      ingest_service.py
      candidate_service.py
      graph_service.py
```


## 4. DB 詳細設計

初期実装の DB は SQLite とする。
ファイル名は仮に `uc_rainfall.sqlite3` を第一候補とする。


### 4.1 datasets

用途:

- 取り込み単位を識別する

想定 DDL:

```sql
CREATE TABLE datasets (
  dataset_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_dir TEXT NOT NULL,
  time_start TEXT,
  time_end TEXT,
  crs_raw TEXT,
  created_at TEXT NOT NULL
);
```

備考:

- 時刻は JST の ISO8601 文字列で保存する
- `dataset_id` は入力ディレクトリ名またはユーザー指定値を使用する
- `source_dir` には元の入力位置を保存し、ZIP 指定時は ZIP ファイルパスを記録する


### 4.2 grids

用途:

- 格子定義を保存する

想定 DDL:

```sql
CREATE TABLE grids (
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
```

備考:

- `origin_x`, `origin_y` は格子基準座標
- CRS は元データ定義に従って保存する


### 4.3 cell_timeseries

用途:

- 各セルの 1時間雨量時系列を保存する

想定 DDL:

```sql
CREATE TABLE cell_timeseries (
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
```

推奨インデックス:

```sql
CREATE INDEX idx_cell_timeseries_dataset_time
  ON cell_timeseries (dataset_id, observed_at);

CREATE INDEX idx_cell_timeseries_dataset_cell
  ON cell_timeseries (dataset_id, row, col);
```


### 4.4 polygons

用途:

- 流域ポリゴンのメタ情報を保存する

想定 DDL:

```sql
CREATE TABLE polygons (
  polygon_id TEXT PRIMARY KEY,
  polygon_name TEXT NOT NULL,
  polygon_group TEXT,
  polygon_crs TEXT NOT NULL,
  minx REAL NOT NULL,
  miny REAL NOT NULL,
  maxx REAL NOT NULL,
  maxy REAL NOT NULL,
  geometry_wkt TEXT NOT NULL
);
```

備考:

- 初期実装では geometry 本体を `geometry_wkt` として DB に保存する
- 元ファイルパスも保持し、必要に応じてファイル側とも照合できるようにする


### 4.5 polygon_cell_map

用途:

- 流域とセルの対応関係を保存する

想定 DDL:

```sql
CREATE TABLE polygon_cell_map (
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
```

推奨インデックス:

```sql
CREATE INDEX idx_polygon_cell_map_dataset_polygon
  ON polygon_cell_map (dataset_id, polygon_id);
```

備考:

- `inside_flag` は `0/1`
- 初期実装の `selection_method` は `cell_intersects_polygon`
- `overlap_ratio` は `overlap_area / cell_area`


## 5. フェーズ1 詳細設計

### 5.1 入力

入力:

- UC-tools ダウンロードディレクトリまたは ZIP ファイル
- 流域ポリゴンディレクトリ

期待ファイル:

- `rain.dat`
- 関連ラスタファイル群
- メール本文ファイル

補足:

- ZIP 入力時は一時ディレクトリへ展開して処理する
- `mail_txt.txt` が存在しない場合は、TIFF の GeoTransform から格子定義を取得する
- 初期実装では複数入力パスを順次取り込める


### 5.2 処理順

1. 入力ディレクトリの存在確認
2. `rain.dat` の存在確認
3. 関連ファイル名から JST 時刻候補抽出
4. `rain.dat` ブロック数と時刻列の整合確認
5. 格子定義抽出
6. `cell_timeseries` レコード生成
7. 同一格子既存データとの重複チェック
8. 流域ポリゴン読込
9. ポリゴン BBox 保存
10. 候補セル抽出
11. `polygon_cell_map` 保存


### 5.3 時刻復元詳細

優先順位:

1. `_JST_YYYYMMDD_HHMMSS`
2. UTC 相当ファイル名から JST 変換
3. `rain.dat` 先頭の経過秒
4. メール本文期間

保存形式:

- JST の ISO8601 文字列
- 例: `2025-01-01T03:00:00`

異常時:

- 時刻数と `rain.dat` ブロック数が一致しない場合はエラー
- 復元不能時は取り込み失敗


### 5.4 rain.dat 解析詳細

前提:

- 各時間ブロックは先頭に `elapsed_seconds rows cols`
- 続く行に格子値本体を持つ

扱い:

- `elapsed_seconds` は補助情報として扱う
- `rows`, `cols` は格子定義とブロック整合確認に利用する
- 値は `row`, `col` ごとに時系列へ展開する


### 5.5 セル中心座標の計算

各セルに対して以下を計算する。

- `x_center`
- `y_center`

計算に必要な情報:

- 基準座標
- セル幅
- セル高
- `row`, `col`

初期実装ではセル中心座標を保持し、空間判定時にはセルポリゴンも内部生成して用いる。


### 5.6 空間判定

初期実装の空間判定:

1. ポリゴン BBox とセルポリゴン BBox の重なりで候補化
2. セルポリゴンと流域ポリゴンの `intersects` 判定で確定

判定結果:

- 採用セルは `polygon_cell_map` へ保存
- `inside_flag=1`
- `selection_method='cell_intersects_polygon'`
- `cell_timeseries` には採用セルに対応する時系列だけを保存する


### 5.7 重複登録判定

対象:

- 同一格子定義を持つ既存 `dataset_id`

判定ルール:

1. `grid_crs`, `origin_x`, `origin_y`, `cell_width`, `cell_height`, `rows`, `cols` が一致する既存データセットを探す
2. 完全一致なら登録をスキップする
3. 重複時刻があり、対応セル値がすべて一致する場合は登録を許可する
4. 重複時刻があり、対応セル値に不一致がある場合はエラーとする

備考:

- 部分的に期間が重なっていて、重複時刻の値がすべて一致する場合は登録を許可する
- この場合、可視化時には同一格子系列として後段で結合される

完全一致の例:

- 同じ格子
- 同じ `observed_at`
- 同じ `row/col`
- 同じ `rainfall_mm`

不整合の例:

- 同じ格子
- 同じ `observed_at`
- 同じ `row/col`
- `rainfall_mm` が異なる


## 6. フェーズ2 詳細設計

### 6.1 入力

入力パラメータ:

- `dataset_id`（任意）
- `polygon_id` または `polygon_name`
- `row`
- `col`
- `local_row`
- `local_col`
- `view_start`
- `view_end`
- 出力ディレクトリ

備考:

- `local_row`, `local_col` を優先的な指定方法とする
- `row`, `col` は内部処理互換のため残す
- `dataset_id` 未指定時は、位置一致する全データセットを対象にする


### 6.2 候補ビュー

初期実装では CLI の一覧表示とする。

表示項目:

- `polygon_name`
- `polygon_local_row`
- `polygon_local_col`
- `x_center`
- `y_center`
- `inside_flag`
- `overlap_ratio`

出力順:

- `polygon_name`
- `polygon_local_row`
- `polygon_local_col`

将来拡張:

- CSV 出力
- GUI 表示
- 地図上の可視化


### 6.2a 系列モード

初期実装では以下の系列モードを持つ。

- `cell`
- `polygon_sum`
- `polygon_mean`
- `polygon_weighted_sum`
- `polygon_weighted_mean`

`cell` の場合は `row`, `col` 指定を必須とする。
`polygon_sum`, `polygon_mean` の場合は流域内候補セル全体を対象にする。


### 6.3 表示期間と内部計算期間

ユーザー指定:

- `view_start`
- `view_end`

内部計算:

- `calc_start = view_start - max_window`
- `calc_end = view_end`

ここで `max_window` は最大累加時間幅に応じて決まる。
初期実装では 48時間を最大とする。

同一格子定義を持つ複数 `dataset_id` が存在する場合は、可視化時にそれらを結合対象とする。
格子一致判定は `grid_crs`, `origin_x`, `origin_y`, `cell_width`, `cell_height`, `rows`, `cols` の一致で行う。
セル単位グラフでは、さらに同一流域内で `x_center`, `y_center` が一致する候補セルのみを結合対象とする。


### 6.4 累加雨量計算

対象指標:

- 1時間
- 3時間
- 6時間
- 12時間
- 24時間
- 48時間

計算方法:

- trailing rolling sum
- `min_periods = window`

欠測:

- 期間先頭で必要時間幅を満たさない場合は `NaN`
- 欠測を 0 に置換しない

重複時刻:

- 同一 `observed_at` が複数 `dataset_id` に存在する場合は、起点 `dataset_id` を優先する
- 採用されなかった他 `dataset_id` はログ出力する


### 6.5 最大イベント抽出

対象:

- 指標ごとに 1件

ルール:

1. 表示対象期間内で最大値を求める
2. 最大値が複数ある場合は最初の発生時刻を採用する
3. 他の同値候補はログ出力する

ログ例:

```text
[INFO] metric=24h max=123.4 first=2025-01-01T03:00:00 duplicate_times=['2025-01-01T04:00:00']
```


### 6.6 イベント切り出し幅

参考実装準拠で、指標ごとに個別の切り出し幅を持つ。

想定設定:

- 1時間: 合計24時間
- 3時間: 合計48時間
- 6時間: 合計48時間
- 12時間: 合計72時間
- 24時間: 合計72時間
- 48時間: 合計96時間

ラベル間隔も指標ごとに持つ。


### 6.7 グラフ出力

出力単位:

- `1セル × 1指標 = 1画像`
- `1流域 × 1集計方法 × 1指標 = 1画像`

最大出力枚数:

- 6枚

ファイル名第一候補:

```text
{dataset_id}_{polygon_name}_lr{local_row}_lc{local_col}_{metric}_{event_time_jst}.png
```

例:

```text
rain126675021_東除川流域_lr12_lc34_24h_20250101T030000JST.png
```

流域集計例:

```text
rain121261948_東除川流域_西除川流域_全セル合計_24h_20250101T230000JST.png
```


## 7. CLI 詳細設計

### 7.1 取り込みコマンド

用途:

- フェーズ1実行

例:

```bash
uv run python -m uc_rainfall.cli ingest \
  --dataset-id rain126675021 \
  --input-path data/rain_download_121261948.zip \
  --polygon-dir data/大阪狭山市_流域界 \
  --db-path outputs/uc_rainfall.sqlite3
```

複数入力例:

```bash
uv run python -m uc_rainfall.cli ingest \
  --input-path data/uc_data_zip/rain_download_121261948.zip \
  --input-path data/uc_data_zip/rain_download_126675021.zip \
  --input-path data/uc_data_zip/rain_download_191300475.zip \
  --db-path outputs/uc_data_zip_trim.sqlite3
```


### 7.2 候補一覧コマンド

用途:

- 候補セルビュー表示

例:

```bash
uv run python -m uc_rainfall.cli list-cells \
  --db-path outputs/uc_rainfall.sqlite3 \
  --dataset-id rain126675021 \
  --polygon-name 東除川流域
```


### 7.3 グラフ生成コマンド

用途:

- フェーズ2実行

例:

```bash
uv run python -m uc_rainfall.cli plot \
  --db-path outputs/uc_rainfall.sqlite3 \
  --dataset-id rain126675021 \
  --polygon-name 東除川流域 \
  --row 12 \
  --col 34 \
  --view-start 2025-01-01T00:00:00 \
  --view-end 2025-01-03T23:00:00 \
  --out-dir outputs/charts
```

備考:

- `plot` は指定 `dataset_id` だけでなく、同一格子定義を持つ他の `dataset_id` も内部的に束ねて利用する
- `dataset_id` を省略した場合は、位置一致する全データセットを内部的に束ねて利用する

流域集計例:

```bash
uv run python -m uc_rainfall.cli plot \
  --db-path outputs/uc_rainfall.sqlite3 \
  --dataset-id rain121261948 \
  --polygon-name "東除川流域 + 西除川流域" \
  --series-mode polygon_sum \
  --view-start 2025-01-01T00:00:00 \
  --view-end 2025-01-03T23:00:00 \
  --out-dir outputs/charts
```


## 8. エラー処理

最低限の異常系:

- 入力ディレクトリ不存在
- `rain.dat` 不在
- 時刻復元失敗
- ポリゴンファイル不存在
- 候補セルゼロ
- 指定 `row/col` が候補セルに含まれない
- 指定期間に有効データが存在しない

対応:

- CLI 終了コード非0
- 原因をメッセージ出力


## 9. ログ設計

最低限のログ対象:

- 取り込み開始/終了
- 時刻復元結果
- 格子定義
- ポリゴン読込結果
- 候補セル数
- グラフ対象セル
- 期間指定
- 指標ごとの最大イベント
- 同値最大候補


## 10. 将来拡張の接続点

詳細設計上、以下は拡張可能な構造にしておく。

- `polygon_timeseries` の追加
- GUI 候補ビュー
- Web API
- 流域代表時系列生成
- JAXA データ統合
