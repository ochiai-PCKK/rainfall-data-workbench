# UC Rainfall ZIP Flow 設計

## 1. 設計方針

- DB 非依存のバッチ処理とする
- 基準日 `YYYY-MM-DD` を入力に、前後2日を含む5日（120時間）を単位として処理する
- ZIP は3日単位を前提に、対象5日と期間が重なる ZIP（最大3件）を採用する
- `raster` / `raster_bbox` 出力は `EPSG:4326`（緯度経度）で実施する
- グラフ重み計算は `EPSG:6674` 系で実施する
- 4領域は BBox 矩形で切り出す
- NoData は `-9999` を `tiff/asc` 共通値として扱う

## 2. モジュール構成

`uc_rainfall_zipflow` は以下のモジュールで構成する。

- `cli.py`
- `application.py`
- `zip_selector.py`
- `zip_reader.py`
- `time_series_builder.py`
- `spatial_clip.py`
- `raster_writer.py`
- `graph_builder.py`
- `logger.py`
- `models.py`

## 3. モジュール責務

### 3.1 `cli.py`

- 実行オプションを受け取る
- 入力チェック（必須引数、日付形式、ディレクトリ存在）
- `--regions` で対象流域を選択する
- `--outputs` で `raster`, `raster_bbox`, `plots` を切り替える
- `application.run(...)` を呼び出す

### 3.2 `application.py`

- 全体オーケストレーション
- 出力ディレクトリ作成
- 各処理フェーズの順序制御
- 失敗時終了コードの制御

### 3.3 `zip_selector.py`

- 入力ルート（デフォルト `outputs\uc_download\downloads`）を走査
- ZIP 名またはメタ情報から期間を解釈
- 対象5日と重なる ZIP を抽出（最大3件）
- 抽出件数不足時はエラー

### 3.4 `zip_reader.py`

- 対象 ZIP を一時ディレクトリへ展開
- 必要ファイル（`tiff`）の読み出し
- ZIP 単位のファイル構成検証

### 3.5 `time_series_builder.py`

- 1時間間隔の 120 点タイムラインを生成
- 対象ファイルを時刻対応づけして整列
- 120点未満/超過や欠落を検知してエラー

### 3.6 `spatial_clip.py`

- `raster` 向けに `EPSG:4326` のまま切り出し、流域外を NoData `-9999` マスクする
- `raster_bbox` 向けに `EPSG:4326` のまま BBox 切り出しのみ実施する
- `plots` 向けに `EPSG:6674` へ変換し、重み計算用の流域切り出しを行う
- `raster_bbox` 向けに BBox 切り出しのみ（NoData マスクなし、0以上へ正規化）を提供する

### 3.7 `raster_writer.py`

- `tiff` と `asc` を出力
- `asc` ヘッダ（`ncols/nrows/xllcorner/yllcorner/DX/DY`）を再計算
- `raster_bbox/{region_key}/rain.dat`（120ブロック）を出力する
- 出力命名規則に沿って保存

### 3.8 `graph_builder.py`

- 指標 `1/3/6/12/24/48` の累加系列を計算
- `-9999` は欠損として除外
- 各指標の最大イベント時刻を抽出してグラフ生成
- 同値最大は先頭採用、他候補はログ出力

### 3.9 `logger.py`

- `--enable-log` 時のみ `logs/{base_date}.log` 出力
- 対象ZIP、処理件数、同値最大候補、エラー情報を記録

### 3.10 `models.py`

- `RunConfig`, `RegionSpec`, `TimeSlot`, `RasterFrame`, `EventSummary` などのデータモデル定義

## 4. 処理フロー

1. 設定読込（基準日、入力ルート、出力ルート、ログ有無）
2. 5日ウィンドウ算出
3. ZIP探索（重なり採用、最大3件）
4. ZIP展開
5. 120点時系列の構築
6. 領域別に座標変換 + BBox切り出し + NoDataマスク
7. 領域別に `tiff/asc` 出力
8. 領域別に6指標グラフ出力
9. ログ出力と終了

## 5. 出力構成

出力ルート:

- `outputs/uc_rainfall_zipflow/{base_date}/`

配下:

- `raster/{region_key}/{region_key}_{YYYYMMDDHH}.tif`
- `raster/{region_key}/{region_key}_{YYYYMMDDHH}.asc`
- `raster_bbox/{region_key}/rain_{region_key}_{YYYYMMDDHH}.tif`
- `raster_bbox/{region_key}/rain.dat`
- `plots/{region_key}/{region_key}_{duration_h}h_{event_YYYYMMDDHH}.png`
- `logs/{base_date}.log`（`--enable-log` 時のみ）

## 6. エラー方針

- ZIP不足、時系列120点不一致、CRS変換失敗、必須ファイル欠落は即時エラー終了
- NoData 補完での継続はしない

## 7. 性能方針

- ZIPは逐次展開し、処理後に一時ファイルを破棄する
- 必要最小限の配列保持でメモリを抑える
- 領域別処理は将来的に並列化可能な構造にする
