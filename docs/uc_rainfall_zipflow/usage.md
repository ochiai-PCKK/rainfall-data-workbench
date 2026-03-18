# UC Rainfall ZIP Flow 利用手順

GUI利用手順は [usage_gui.md](./usage_gui.md) を参照してください。

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
- `--regions`: 対象流域キー（カンマ区切り、既定: `nishiyoke_higashiyoke`）
- `--outputs`: 出力種別（`raster,raster_bbox,plots,plots_ref,analysis_csv` からカンマ区切り、既定: `raster,raster_bbox,plots_ref`）
  - `plots`: 既存スタイル
  - `plots_ref`: 整形時系列グラフ（`plots_reference` に出力）
  - `analysis_csv`: 分析CSVセット（`*_timeseries.csv`, `*_cells.csv`, `README_ja.txt`）
  - 互換: `timeseries_csv` も指定可能（内部的に `analysis_csv` と同義）
- `--window-mode`: 探索期間指定方法（`offset` / `range`）
- `--days-before`, `--days-after`: `window-mode=offset` 時の探索幅
- `--start-date`, `--end-date`: `window-mode=range` 時の探索期間
- `--graph-spans`: `plots_ref` の対象期間（`3d,5d` など）
- `--ref-graph-kinds`: `plots_ref` の出力種別（`sum`, `mean`）
- `--export-svg`: PNG に加えて SVG も出力
- `--style-profile`: `plots_ref` に適用するスタイルプロファイル(JSON)
- `--on-conflict`: 出力衝突時の挙動（`rename` / `overwrite` / `cancel`、既定は `rename`）

例: 西除川+東除川のみ、整形時系列グラフとラスタを出力

```powershell
uv run python -m uc_rainfall_zipflow.cli run --base-date 2010-07-14 --enable-log --regions nishiyoke_higashiyoke --outputs raster,raster_bbox,plots_ref
```

例: 期間指定 + 3日グラフ（平均のみ）

```powershell
uv run python -m uc_rainfall_zipflow.cli run --base-date 2010-07-14 --window-mode range --start-date 2010-07-13 --end-date 2010-07-15 --outputs plots_ref,analysis_csv --graph-spans 3d --ref-graph-kinds mean
```

## 1.1 グラフスタイル調整 GUI

`*_timeseries.csv` を入力に体裁を調整し、JSONプロファイル保存ができる。
`--input-csv` を省略した場合は、疑似データ（`--sample-mode synthetic`）で起動できる。
`--preview-span` でプレビュー期間を `3d` / `5d` 切替できる（GUI内でも切替可）。

使い分け:
- 分析CSVを出力済みの場合: その `*_timeseries.csv` を指定して実データで調整
- 分析CSVがない場合: `--input-csv` 省略でテンプレート（疑似データ）調整
- 保存運用: 通常は「既定先へ保存」、必要時のみ「名前を付けて保存」

推奨配置:

- 運用用: `config/uc_rainfall_zipflow/styles/default.json`
- 実験用: `outputs/style_profiles/*.json`

```powershell
uv run python -m uc_rainfall_zipflow.cli style-gui --input-csv outputs\_tmp_zipflow_csv4\2010-07-14\analysis_csv\nishiyoke_higashiyoke\nishiyoke_higashiyoke_20100714_timeseries.csv --value-kind mean --profile-path config\uc_rainfall_zipflow\styles\default.json
```

CSVなしで起動（まず体裁だけ調整）:

```powershell
uv run python -m uc_rainfall_zipflow.cli style-gui --value-kind mean --sample-mode synthetic --preview-span 3d --profile-path config\uc_rainfall_zipflow\styles\default.json
```

プロファイル適用例:

```powershell
uv run python -m uc_rainfall_zipflow.cli run --base-date 2010-07-14 --outputs plots_ref --ref-graph-kinds mean --style-profile config\uc_rainfall_zipflow\styles\default.json
```

## 1.2 実行 GUI（新規）

`run` 相当の実行を GUI で行う場合:

```powershell
uv run python -m uc_rainfall_zipflow.cli gui
```

起動テスト（自動終了）:

```powershell
uv run python -m uc_rainfall_zipflow.cli gui --test-mode
```

`--test-mode` では、起動後に以下を実行して自動終了する。
- 必須ウィジェット存在確認
- GUI全体スクリーンショット保存（`outputs/_gui_test/startup_*.png`）
- テスト結果JSON保存（`outputs/_gui_test/startup_*.json`）

主な仕様:
- 既存GUIの再利用はせず、`uc_rainfall_zipflow` 専用画面として実装
- 期間指定は `開始日/終了日`（`YYYY-MM-DD`）で、3日または5日のみ許可
- 設定キャッシュ: `config/uc_rainfall_zipflow/gui_state.json`
- 右ペインに実行ログ・生成物サマリ・グラフスタイル調整導線を表示

## 2. 出力構成

基準日 `2010-07-14` の場合:

- `outputs/uc_rainfall_zipflow/2010-07-14/raster/{region_key}/*.tif`
- `outputs/uc_rainfall_zipflow/2010-07-14/raster/{region_key}/*.asc`
- `outputs/uc_rainfall_zipflow/2010-07-14/raster_bbox/{region_key}/*.tif`
- `outputs/uc_rainfall_zipflow/2010-07-14/raster_bbox/{region_key}/rain.dat`
- `outputs/uc_rainfall_zipflow/2010-07-14/plots/{region_key}/*.png`
- `outputs/uc_rainfall_zipflow/plots_reference/*_sum_overview.png`
- `outputs/uc_rainfall_zipflow/plots_reference/*_mean_overview.png`
- `outputs/uc_rainfall_zipflow/plots_reference/*.svg`（`--export-svg` 時）
- `outputs/uc_rainfall_zipflow/2010-07-14/analysis_csv/{region_key}/*_timeseries.csv`
- `outputs/uc_rainfall_zipflow/2010-07-14/analysis_csv/{region_key}/*_cells.csv`
- `outputs/uc_rainfall_zipflow/2010-07-14/analysis_csv/README_ja.txt`
- `outputs/uc_rainfall_zipflow/2010-07-14/logs/2010-07-14.log`（ログ有効時）

`region_key`:

- `nishiyoke`
- `higashiyoke`
- `nishiyoke_higashiyoke`
- `yamatogawa`（ポリゴンが存在する場合のみ）

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
