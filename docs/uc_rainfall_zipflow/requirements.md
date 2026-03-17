# UC Rainfall ZIP Flow 要件定義

## 1. 文書の目的

本書は `uc_rainfall_zipflow` における、ZIP 直接処理でのデータ生成・グラフ生成要件を定義する。  
対象データは UC-tools ダウンロード ZIP とし、JAXA 系データは対象外とする。

## 2. スコープ

### 2.1 対象

- 基準日入力からの対象 ZIP 探索
- ZIP の一時展開
- 4領域（BBox）での空間切り出し
- `tiff` / `asc` 生成
- 同一期間データを用いたグラフ生成

### 2.2 対象外

- CSV 出力
- DB 永続化を前提とした処理
- GUI 詳細仕様

## 3. 入力要件

- 入力ルートのデフォルト: `outputs\uc_download\downloads`
- ユーザー入力: 基準日 `YYYY-MM-DD`
- 処理対象期間: 基準日の前後2日を含む5日間
- ZIP 探索は「対象5日と期間が重なる ZIP」を採用する
- UC-tools ZIP は3日単位を前提とし、採用 ZIP 数は最大 3 件とする
- ZIP 不足時は処理を継続せずエラー終了とする

## 4. 時間要件

- 時系列は 1 時間間隔とする
- 出力点数は 120 点（5日 x 24時間）とする
- 相対時刻は秒で保持し、`0` から `428400`（3600秒刻み）を採用する
- `432000` は終端秒として扱わず、系列点には含めない
- 欠損時刻の NoData 補完は行わず、時系列が 120 点揃わない場合はエラー終了とする

## 5. 空間要件

- 空間対象は 4領域（西除川・東除川・西除川+東除川・大和川流域）とする
- 判定はポリゴン厳密判定ではなく BBox 矩形で実施する
- ZIP 由来ラスタは `EPSG:4326` 前提とする
- `raster` / `raster_bbox` は `EPSG:4326`（緯度経度）で出力する
- グラフ計算用の空間重み処理は `EPSG:6674` 系で実施する
- `raster` / `raster_bbox` は入力ZIP内TIFFの格子情報（`xll/yll/DX/DY` 相当）を基準に生成する
- CRS 変換失敗時は処理中断とする
- グラフ計算では基準時刻の格子を基準とし、不一致格子が含まれる場合はエラー終了とする

## 6. 出力要件

### 6.1 データ出力

- 5日間を単一期間として `tiff` と `asc` を生成する
- 出力ルートは `outputs/uc_rainfall_zipflow/{base_date}/` とする
- 出力サブディレクトリは `raster/`, `raster_bbox/`, `plots/`, `logs/` とする
- `raster/` は解析用ディレクトリとし、`tiff` と `asc` を同一階層で管理する
- `raster_bbox/` は ZIP 展開再現ディレクトリとし、各領域で `rain.dat` と時刻TIFFを管理する
- 各出力は領域キー単位のサブディレクトリで管理する
  - 例: `.../plots/nishiyoke/`
  - 領域キー: `nishiyoke`, `higashiyoke`, `nishiyoke_higashiyoke`, `yamatogawa`
- `base_date` は `YYYY-MM-DD` 文字列を採用する

命名規則:

- `tiff`: `raster/{region_key}/{region_key}_{YYYYMMDDHH}.tif`
- `asc`: `raster/{region_key}/{region_key}_{YYYYMMDDHH}.asc`
- `raster_bbox tiff`: `raster_bbox/{region_key}/rain_{region_key}_{YYYYMMDDHH}.tif`
- `raster_bbox rain.dat`: `raster_bbox/{region_key}/rain.dat`
- `plot`: `plots/{region_key}/{region_key}_{duration_h}h_{event_YYYYMMDDHH}.png`
- `log`: `logs/{base_date}.log`（テキスト、ログ出力有効時のみ）

### 6.2 `asc` 仕様

- クリップ後の `ncols` / `nrows` / `xllcorner` / `yllcorner` を再計算する
- `DX` / `DY` を明示出力する
- 実データ行数・列数はメタデータと一致させる
- ラスタ NoData 値は `-9999` で固定する（`tiff` / `asc` 共通）
- NoData は空間欠損セルを表す値として扱い、時系列欠損補完には使わない
- 集計・最大値計算では `-9999` を欠損として除外する

### 6.3 グラフ出力

- グラフは 6 指標（1/3/6/12/24/48 時間）を対象とする
- 指標ごとに最大値を記録した時刻を中心に出力する
- 同値最大が複数ある場合は先頭時刻を採用し、他候補時刻を `run.log` に出力する
- グラフ書式は既存処理を参考とする

## 7. 非機能要件

- 大量 ZIP を前提に逐次処理で完了できること
- 実行ログで対象日・対象 ZIP・欠損日・失敗理由を追跡できること
- 同一入力・同一条件で再実行時に再現性があること
- ログ出力はオプションで有効化できること

## 8. 受け入れ条件

- 基準日入力で対象5日を探索できる
- 120点（`0..428400` 秒）の時系列で処理される
- 4領域それぞれで `tiff` / `asc` が生成される
- `asc` メタデータと実データサイズが一致する
- `raster_bbox/{region_key}/rain.dat` が 120 ブロックで生成される
- 6 指標の最大イベントグラフが出力される
