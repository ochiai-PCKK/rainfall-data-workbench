# UC Rainfall ZIP Flow 利用手順

## 1. 実行コマンド

```powershell
uv run python -m uc_rainfall_zipflow.cli run --base-date 2010-07-14 --enable-log
```

主な引数:

- `--base-date`: 基準日（必須, `YYYY-MM-DD`）
- `--input-zipdir`: 入力 ZIP ディレクトリ（既定: `outputs\uc_download\downloads`）
- `--output-dir`: 出力ルート（既定: `outputs\uc_rainfall_zipflow`）
- `--polygon-dir`: ポリゴンディレクトリ（既定: `data\大阪狭山市_流域界`）
- `--enable-log`: ログ出力有効化（`logs/{base_date}.log` を生成）
- `--regions`: 対象流域キー（カンマ区切り）
- `--outputs`: 出力種別（`raster,raster_bbox,plots,plots_ref` からカンマ区切り）
  - `plots`: 既存スタイル
  - `plots_ref`: 参考画像寄せスタイル（`plots_reference` に出力）

例: 西除川+東除川のみ、グラフとラスタを全出力

```powershell
uv run python -m uc_rainfall_zipflow.cli run --base-date 2010-07-14 --enable-log --regions nishiyoke_higashiyoke --outputs raster,raster_bbox,plots
```

## 2. 出力構成

基準日 `2010-07-14` の場合:

- `outputs/uc_rainfall_zipflow/2010-07-14/raster/{region_key}/*.tif`
- `outputs/uc_rainfall_zipflow/2010-07-14/raster/{region_key}/*.asc`
- `outputs/uc_rainfall_zipflow/2010-07-14/raster_bbox/{region_key}/*.tif`
- `outputs/uc_rainfall_zipflow/2010-07-14/raster_bbox/{region_key}/rain.dat`
- `outputs/uc_rainfall_zipflow/2010-07-14/plots/{region_key}/*.png`
- `outputs/uc_rainfall_zipflow/2010-07-14/plots_reference/{region_key}/*.png`
- `outputs/uc_rainfall_zipflow/2010-07-14/logs/2010-07-14.log`（ログ有効時）

`region_key`:

- `nishiyoke`
- `higashiyoke`
- `nishiyoke_higashiyoke`
- `yamatogawa`

## 3. 期待結果

- 採用 ZIP 数: 最大3件（対象5日に重なる3日ZIP）
- 時系列点数: 120点（`0..428400`秒）
- 各領域: `tif`120件 + `asc`120件
- グラフ: 6指標（1/3/6/12/24/48h）x 4領域 = 24枚

## 4. 終了コード

- `0`: 正常終了
- `2`: 引数不正（argparse）
- `3`: ZIP 選定失敗
- `4`: データ読込失敗
- `5`: 時系列整合失敗（120点不足など）
- `6`: 空間処理失敗（CRS/BBox）
- `7`: 出力書込失敗
