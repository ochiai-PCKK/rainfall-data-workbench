# UC Rainfall ZIP Flow 詳細設計

## 1. 目的

本書は `requirements.md` と `design.md` を実装可能な粒度に落とし込み、入出力仕様・アルゴリズム・エラー条件を定義する。

## 2. CLI 仕様

想定コマンド:

`uv run python -m uc_rainfall_zipflow.cli run`

主要オプション:

- `--base-date YYYY-MM-DD`（必須）
- `--input-zipdir PATH`（任意、未指定時は `outputs\uc_download\downloads`）
- `--output-dir PATH`（任意、未指定時は `outputs/uc_rainfall_zipflow`）
- `--regions CSV`（任意、未指定時は全4流域）
- `--outputs CSV`（任意、未指定時は `raster,raster_bbox,plots`。`plots_ref` も指定可）
- `--enable-log`（任意）

終了コード:

- `0`: 正常終了
- `2`: 引数不正
- `3`: ZIP探索失敗（不足・期間不一致）
- `4`: データ読込失敗
- `5`: 時系列120点不一致
- `6`: CRS変換/空間処理失敗
- `7`: 出力書込失敗

## 3. データモデル

### 3.1 `RunConfig`

- `base_date: date`
- `input_zipdir: Path`
- `output_root: Path`
- `enable_log: bool`
- `region_keys: tuple[str, ...]`
- `output_kinds: tuple[str, ...]`

### 3.2 `RegionSpec`

- `region_key: str`
- `region_name: str`
- `bbox_6674: tuple[float, float, float, float]`（`minx, miny, maxx, maxy`）

固定定義:

- `nishiyoke`
- `higashiyoke`
- `nishiyoke_higashiyoke`
- `yamatogawa`

### 3.3 `TimeSlot`

- `index: int`（0..119）
- `observed_at_jst: datetime`
- `relative_seconds: int`（0..428400）

### 3.4 `RasterFrame`

- `slot: TimeSlot`
- `array: ndarray[float32]`
- `transform: Affine`
- `crs: str`
- `nodata: float = -9999.0`

## 4. アルゴリズム詳細

## 4.1 対象期間計算

- `base_date` の `00:00:00` JST を基準とする
- 期間開始: `base_date - 2 days 00:00`
- 期間終了: `base_date + 2 days 23:00`
- 1時間刻みで120スロットを生成

## 4.2 ZIP選定

- ZIP名から期間開始・終了を解釈（正規表現で日付抽出）
- 条件: `[zip_start, zip_end]` と対象5日が重なるもの
- 採用上限は3件
- 採用件数が必要条件を満たさない場合は終了コード`3`

## 4.3 展開とフレーム抽出

- 採用 ZIP を一時ディレクトリへ展開
- 対象 `tiff` を列挙
- 各ファイルの観測時刻を抽出し `TimeSlot` に割当
- 割当後に 120 スロット完全性チェック

## 4.4 座標処理と切り出し

- 入力ラスタCRSを確認する
- `raster` 向けに `EPSG:4326` のまま切り出し、流域外を `-9999` マスク
- `raster_bbox` 向けに `EPSG:4326` のまま BBox 切り出しのみ実施（NoDataマスクなし、値は0以上へ正規化）
- `plots` 向けに `EPSG:6674` へ変換して重み計算を実施
- `-9999` は集計対象外として扱う

## 4.5 `asc` / `rain.dat` 書き出し

- ヘッダ項目を切り出し後サイズで再計算
  - `ncols`
  - `nrows`
  - `xllcorner`
  - `yllcorner`
  - `DX`
  - `DY`
  - `NODATA_value -9999`
- 本文行列の行数・列数一致を検証して出力

## 4.6 グラフ計算

- 1時間系列を入力に累加系列（1/3/6/12/24/48）を作成
- ローリング窓内に `-9999` が含まれる時刻は欠損として無効化
- 指標ごとに最大値と時刻を抽出
- 同値最大複数時は最初の時刻を採用し、残りはログへ記録

## 5. ファイル出力詳細

出力ルート:

- `{output_dir}/{base_date}/`

出力先:

- `raster/{region_key}/{region_key}_{YYYYMMDDHH}.tif`
- `raster/{region_key}/{region_key}_{YYYYMMDDHH}.asc`
- `raster_bbox/{region_key}/rain_{region_key}_{YYYYMMDDHH}.tif`
- `raster_bbox/{region_key}/rain.dat`
- `plots/{region_key}/{region_key}_{duration_h}h_{event_YYYYMMDDHH}.png`
- `logs/{base_date}.log`（`--enable-log` の場合のみ）

## 6. ログ仕様

ログレベル:

- `INFO`: 探索ZIP、採用ZIP、出力件数、処理時間
- `WARN`: 同値最大の非採用時刻
- `ERROR`: 失敗理由と終了コード

最低出力項目:

- `base_date`
- 対象期間（開始/終了）
- 採用ZIP一覧
- 120点検証結果
- 領域別出力件数
- 失敗時スタック要約

## 7. バリデーション

実行前:

- 入力ディレクトリ存在
- `base_date` 書式

処理中:

- ZIP期間解釈可否
- 120点完全性
- CRS変換可否
- `asc` 行列サイズ整合

実行後:

- 領域別 `tiff/asc` 120件存在
- 6指標グラフ生成確認

## 8. テスト観点

- 正常系: 5日を完全に覆うZIP群で出力成功
- 異常系: ZIP不足で即時失敗
- 異常系: 120点不足で即時失敗
- 異常系: CRS不一致/変換失敗で即時失敗
- 品質: 同値最大時の先頭採用ログ確認
