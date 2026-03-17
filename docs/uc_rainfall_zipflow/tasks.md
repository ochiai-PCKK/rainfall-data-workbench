# UC Rainfall ZIP Flow タスク分解

## 1. 方針

タスクは、要件で確定した「5日単位の ZIP 直接処理」を最短で実装できるよう、  
フェーズを `基盤 -> 変換/出力 -> グラフ -> 検証` の順で進める。

初期実装ゴールは以下とする。

- 基準日 `YYYY-MM-DD` から対象5日を確定できる
- 対象5日と重なる3日ZIPを最大3件まで選定できる
- 4領域（BBox）ごとに `tiff/asc` を120時刻分出力できる
- `-9999` を NoData として統一できる
- 6指標（1/3/6/12/24/48h）の最大イベントグラフを出力できる

## 1.1 ステータス運用ルール

各タスクは以下のいずれかの状態を持つ。

- `done`
  - 実装が存在する
  - 呼び出し経路がつながっている
  - 手元確認または成果物確認がある
- `partial`
  - 一部は実装済みだが、要件を満たし切っていない
  - もしくは実装はあるが確認が不足している
- `pending`
  - 未着手、または実装ファイルがまだない

本書では各タスクに `Status` と `Check` を記載する。

- `Status`
  - `done`, `partial`, `pending`
- `Check`
  - `code`: 実装ファイル確認
  - `manual`: 手動確認または成果物確認
  - `docs`: ドキュメント反映確認
  - `none`: 未確認

## 2. フェーズ1: 基盤・入力

### T1. パッケージ雛形作成

Status: `done`  
Check: `code`

- `src/uc_rainfall_zipflow` パッケージを作成する
- `cli.py`, `application.py`, `models.py` を作成する
- `zip_selector.py`, `zip_reader.py`, `logger.py` を作成する

### T2. 設定/引数モデル実装

Status: `done`  
Check: `code`

- `RunConfig` を実装する
- `--base-date`, `--input-zipdir`, `--output-dir`, `--enable-log` を実装する
- 既定入力ルート `outputs\\uc_download\\downloads` を実装する

### T3. 対象期間・スロット生成実装

Status: `done`  
Check: `code`

- 基準日±2日（120時間）を計算する
- `0..428400` 秒（3600秒刻み）の時刻スロットを生成する
- 120点固定チェックを実装する

### T4. ZIP 選定実装

Status: `done`  
Check: `code`

- ZIP 名から期間を解釈する
- 対象5日と重なる ZIP を抽出する
- 最大3件まで採用する
- 不足時にエラー終了する

### T5. ZIP 展開実装

Status: `done`  
Check: `code`

- 一時ディレクトリへ ZIP を展開する
- 必須ファイル構成を検証する
- 後続処理向けに対象 `tiff` 一覧を返す

## 3. フェーズ2: 空間処理・ラスタ出力

### T6. 領域定義実装

Status: `done`  
Check: `code`

- 4領域の `region_key` と `bbox_6674` を定義する
- 領域キーを命名規則に配線する

### T7. CRS 変換実装

Status: `done`  
Check: `code`

- 入力ラスタ `EPSG:4326` の検証を実装する
- `EPSG:6674` への変換を実装する
- 変換失敗時のエラー終了を実装する

### T8. BBox 切り出し実装

Status: `done`  
Check: `code`

- 4領域 BBox で切り出しを実装する
- 流域外セルを `-9999` に設定する
- `-9999` の型・書式を統一する

### T9. TIFF 出力実装

Status: `done`  
Check: `code`

- `raster/{region_key}/{region_key}_{YYYYMMDDHH}.tif` 出力を実装する
- 120時刻分出力の整合チェックを実装する

### T10. DAT 出力実装

Status: `done`  
Check: `code`

- `raster/{region_key}/{region_key}_{YYYYMMDDHH}.asc` 出力を実装する
- `ncols/nrows/xllcorner/yllcorner/DX/DY/NODATA_value` を再計算する
- 実データ行列との一致検証を実装する

## 4. フェーズ3: グラフ出力

### T11. 重み付き合計系列生成実装

Status: `done`  
Check: `code`

- 領域ごとの重み付き合計 1h 系列を生成する
- `-9999` を欠損として除外する

### T12. 累加系列計算実装

Status: `done`  
Check: `code`

- `1/3/6/12/24/48h` のローリング累加を実装する
- 欠損混入窓の無効化を実装する

### T13. 最大イベント抽出実装

Status: `done`  
Check: `code`

- 各指標の最大時刻を抽出する
- 同値最大時は先頭採用を実装する
- 非採用候補時刻のログ出力を実装する

### T14. グラフ描画実装

Status: `done`  
Check: `code`

- 6指標グラフを描画する
- `plots/{region_key}/{region_key}_{duration_h}h_{event_YYYYMMDDHH}.png` 保存を実装する
- 既存処理準拠の体裁を実装する

## 5. フェーズ4: 実行制御・ログ

### T15. アプリケーション統合実装

Status: `done`  
Check: `code`

- フェーズ1-3を `application.py` で統合する
- エラー時終了コード（3-7）を実装する

### T16. ログ出力実装

Status: `done`  
Check: `code`

- `--enable-log` 時のみ `logs/{base_date}.log` 出力を実装する
- 採用ZIP、120点検証、同値最大候補、エラー理由を出力する

### T17. CLI 実装

Status: `done`  
Check: `code`, `manual`

- `run` コマンドを実装する
- 入力チェックと実行結果サマリ表示を実装する

## 6. フェーズ5: 検証

### T18. 正常系検証

Status: `done`  
Check: `manual`

- 5日を覆うZIP群で実行成功を確認する
- 各領域で `tiff/asc` 120件出力を確認する
- 6指標グラフ出力を確認する

### T19. 異常系検証

Status: `partial`  
Check: `none`

- ZIP不足時のエラー終了を確認する
- 120点不足時のエラー終了を確認する
- CRS変換失敗時のエラー終了を確認する

### T20. NoData 検証

Status: `done`  
Check: `manual`

- `tiff/asc` の NoData が `-9999` で統一されていることを確認する
- 集計・最大値計算で `-9999` が除外されることを確認する

## 7. ドキュメント・仕上げ

### T21. 設計差分反映

Status: `done`  
Check: `docs`

- 実装差分を `requirements.md`, `design.md`, `detailed_design.md` に反映する

### T22. 利用手順作成

Status: `done`  
Check: `docs`

- 実行コマンド例を作成する
- 出力フォルダ構成と確認手順を作成する

## 8. 実装順の推奨

1. T1
2. T2
3. T3
4. T4
5. T5
6. T6
7. T7
8. T8
9. T9
10. T10
11. T11
12. T12
13. T13
14. T14
15. T15
16. T16
17. T17
18. T18
19. T19
20. T20
21. T21
22. T22
