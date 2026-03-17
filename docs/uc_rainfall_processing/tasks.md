# UC降雨処理 タスク分解

## 1. 方針

タスクは、依存関係が明確になるようにフェーズ1、フェーズ2、検証、将来拡張準備に分けて進める。

初期実装では、以下をゴールとする。

- UC-tools データを DB へ取り込める
- 流域ごとの候補セルを抽出できる
- CLI で候補セルを確認できる
- `local_row/local_col` 指定で対象セルを選べる
- 指定期間内の各指標最大イベントグラフを出力できる

## 1.1 ステータス運用ルール

各タスクは以下のいずれかの状態を持つ。

- `done`
  - 実装が存在する
  - 呼び出し経路がつながっている
  - 手元確認または成果物確認がある
- `partial`
  - 一部は実装済みだが、要件を満たし切っていない
  - もしくは実装はあるが確認が不足している
  - もしくは実装とタスク記述に差分がある
- `pending`
  - 未着手、または実装ファイルがまだない

各タスク更新時は、最低限以下を確認する。

- コードの有無
- CLI または呼び出し経路の有無
- outputs やログなどの確認痕跡の有無
- 設計差分の有無

本書では各タスクに `Status` と `Check` を記載する。

- `Status`
  - `done`, `partial`, `pending`
- `Check`
  - `code`: 実装ファイル確認
  - `manual`: 手動確認または成果物確認
  - `docs`: ドキュメント反映確認
  - `none`: 未確認


## 2. フェーズ1: 取り込み・DB格納

### T1. プロジェクト骨組み作成

Status: `done`
Check: `code`

- `src/uc_rainfall` 配下のモジュール構成を作成する
- `cli.py`, `db.py`, `schema.py`, `models.py` の雛形を作る
- `ingest`, `spatial`, `graph`, `services` パッケージを作る


### T2. DB スキーマ実装

Status: `done`
Check: `code`, `manual`

- SQLite 接続処理を実装する
- `datasets`, `grids`, `cell_timeseries`, `polygons`, `polygon_cell_map` の DDL を実装する
- 初期化処理を CLI から呼べるようにする
- 必要インデックスを作成する


### T3. UC-tools 入力ローダ実装

Status: `done`
Check: `code`, `manual`

- 入力ディレクトリ存在確認を実装する
- ZIP ファイル入力を受けて一時展開する処理を実装する
- `rain.dat`、ラスタ群、メール本文の探索処理を実装する
- 必要ファイル一覧を返すローダを作る


### T4. 時刻復元実装

Status: `done`
Check: `code`, `manual`

- TIFF 名から `_JST_YYYYMMDD_HHMMSS` を抽出する処理を実装する
- UTC 相当ファイル名から JST へ変換する補助処理を実装する
- `rain.dat` 経過秒を解釈する補助処理を実装する
- 時刻列確定ロジックを実装する
- `rain.dat` ブロック数との整合確認を実装する


### T5. rain.dat パーサ実装

Status: `done`
Check: `code`, `manual`

- ブロック単位で `elapsed_seconds rows cols` を読む処理を実装する
- 値本体を `row/col` 単位へ展開する処理を実装する
- 格子サイズの整合確認を実装する


### T6. 格子定義・セル中心座標計算実装

Status: `done`
Check: `code`, `manual`

- 基準座標、セル幅、セル高、行数、列数を扱うモデルを作る
- `mail_txt.txt` がない場合に TIFF から格子定義を取得する処理を実装する
- `row/col -> x_center/y_center` 変換処理を実装する
- `cell_timeseries` 用のレコード生成処理を作る


### T7. フェーズ1保存処理実装

Status: `done`
Check: `code`, `manual`

- `datasets` への保存処理を実装する
- `grids` への保存処理を実装する
- `cell_timeseries` への一括保存処理を実装する


### T7a. 重複登録判定実装

Status: `done`
Check: `code`, `manual`

- 同一格子定義を持つ既存 `dataset_id` を特定する
- 完全一致データセットをスキップする処理を実装する
- 重複時刻で値不一致ならエラーにする処理を実装する
- 判定結果をログ出力する


## 3. フェーズ1: 空間対応付け

### T8. ポリゴンローダ実装

Status: `done`
Check: `code`, `manual`

- 流域ポリゴンファイルの読込処理を実装する
- 対象4領域の管理処理を実装する
- `polygon_id`, `polygon_name`, `bbox`, `crs` を抽出する


### T9. polygons 保存処理実装

Status: `done`
Check: `code`, `manual`

- `polygons` テーブルへの保存処理を実装する
- 重複登録時の更新方針を決めて実装する


### T10. 候補セル抽出実装

Status: `done`
Check: `code`, `manual`

- セルポリゴン BBox と流域 BBox の重なりで候補を絞る処理を実装する
- セルポリゴンと流域ポリゴンの `intersects` 判定を実装する
- `cell_intersects_polygon` 方式で採用セルを決定する


### T11. polygon_cell_map 保存処理実装

Status: `done`
Check: `code`, `manual`

- `polygon_cell_map` への保存処理を実装する
- `dataset_id + polygon_id + row + col` の一意性を守る
- `polygon_local_row`, `polygon_local_col` を算出して保存する
- `cell_area`, `overlap_area`, `overlap_ratio` を算出して保存する


### T12. ingest サービス統合

Status: `done`
Check: `code`, `manual`

- フェーズ1全体を `ingest_service.py` で統合する
- `ingest` CLI コマンドから実行できるようにする
- ログ出力を整える


## 4. フェーズ2: 候補セル参照

### T13. 候補セル一覧取得実装

Status: `done`
Check: `code`

- `polygon_cell_map` と `cell_timeseries` を使って候補セル一覧を取得する
- `polygon_name`, `polygon_local_row`, `polygon_local_col`, `x_center`, `y_center`, `inside_flag` を返す


### T14. CLI 候補ビュー実装

Status: `done`
Check: `code`, `manual`

- `list-cells` コマンドを実装する
- 一覧形式で候補セルを表示する
- 並び順を `polygon_name`, `polygon_local_row`, `polygon_local_col` にそろえる
- `polygon_local_row`, `polygon_local_col`, `x_center`, `y_center`, `overlap_ratio` を表示する


## 5. フェーズ2: グラフ生成

### T15. 時系列取得実装

Status: `done`
Check: `code`, `manual`

- `dataset_id + row + col` でセル時系列を取得する
- `dataset_id + polygon_local_row + polygon_local_col` でも起点セルを解決できるようにする
- 同一格子定義を持つ複数 `dataset_id` を特定する
- 可視化時に同一格子の `dataset_id` を結合して時系列を作る
- セル単位では `x_center/y_center` 一致セルだけを結合する
- `view_start`, `view_end` を受け取る
- `calc_start` を内部計算して必要期間を読み出す
- `polygon_sum`, `polygon_mean`, `polygon_weighted_sum`, `polygon_weighted_mean` の流域集計時系列を取得できるようにする


### T16. rolling 指標計算実装

Status: `done`
Check: `code`, `manual`

- 1h, 3h, 6h, 12h, 24h, 48h を計算する処理を実装する
- trailing rolling sum を採用する
- `min_periods = window` を守る
- 欠測を 0 補完しない


### T17. 最大イベント抽出実装

Status: `done`
Check: `code`, `manual`

- 指標ごとの最大値を求める
- 同値最大時は最初の発生時刻を採用する
- 他の同値候補時刻をログ出力する


### T18. イベント切り出し実装

Status: `done`
Check: `code`, `manual`

- 指標ごとの表示幅設定を実装する
- 参考実装準拠の切り出し幅を定数化する
- 発生時刻前後の表示期間を切り出す


### T19. グラフ描画実装

Status: `done`
Check: `code`, `manual`

- 1時間雨量棒グラフを描画する
- 指標別累加雨量折れ線を描画する
- 軸ラベル、タイトル、凡例を実装する
- PNG 出力処理を実装する


### T20. ファイル命名実装

Status: `done`
Check: `code`, `manual`

- `{dataset_id}_{polygon_name}_lr{local_row}_lc{local_col}_{metric}_{event_time_jst}.png` を実装する
- ファイル名安全化処理を入れる


### T21. plot サービス統合

Status: `done`
Check: `code`, `manual`

- フェーズ2全体を `graph_service.py` で統合する
- `plot` CLI コマンドから実行できるようにする


## 6. 検証

### T22. フェーズ1動作確認

Status: `done`
Check: `manual`

- 実データで DB 作成が通ることを確認する
- `datasets`, `grids`, `cell_timeseries`, `polygons`, `polygon_cell_map` に想定件数が入ることを確認する


### T23. 候補ビュー確認

Status: `done`
Check: `manual`

- `list-cells` で候補セル一覧が見えることを確認する
- `polygon_local_row/polygon_local_col` と `x_center/y_center` が妥当であることを確認する


### T24. グラフ出力確認

Status: `done`
Check: `manual`

- 1セルを選び、6指標分の PNG が出ることを確認する
- 同値最大時ログが出ることを確認する
- 期間指定が反映されることを確認する


### T25. 境界ケース確認

Status: `partial`
Check: `code`, `manual`

- 候補セルゼロ
- 指定 `local_row/local_col` 不正
- 指定期間にデータなし
- 48時間未満のデータ
- 欠測を含むデータ
- 同一格子で複数 `dataset_id` が存在するケース
- 同一 `observed_at` が重複するケース


## 7. ドキュメント・仕上げ

### T26. README 追記

Status: `pending`
Check: `none`

- セットアップ方法
- DB 初期化方法
- `ingest`, `list-cells`, `plot` の使用例


### T27. 設計との差分反映

Status: `partial`
Check: `docs`

- 実装途中で変更した仕様を `requirements.md`, `design.md`, `detail_design.md` に反映する


## 8. GUI リファクタリング準備

### T28. GUI モジュール分割方針反映

Status: `done`
Check: `docs`

- `gui_design.md` に GUI モジュール分割方針を追記する
- `gui_implementation_plan.md` に分離対象ファイルと分離順序を追記する
- `app.py` は起動入口と配線を主責務とする方針を明記する


### T29. GUI モジュール分割実施

Status: `done`
Check: `code`, `docs`

- `test_mode.py` を `app.py` から切り出す
- `validation.py` を `app.py` から切り出す
- `layout.py` を `app.py` から切り出す
- `actions.py` を `app.py` から切り出す
- 切り出し後に `ruff` と `pyright` を再確認する


## 10. DB スリム化

### T30. `quality` 列削減

Status: `done`
Check: `code`, `manual`

- `cell_timeseries.quality` の保存を停止する
- 参照SQLと挿入SQLを更新する
- 既存DB向け移行手順を整理する


### T31. `x_center/y_center` 非保存化

Status: `pending`
Check: `none`

- `cell_timeseries` から `x_center`, `y_center` を削減する
- `candidate_service.py` と `spatial_view_service.py` で座標再計算を実装する
- 面ビュー・候補一覧の回帰確認を行う


### T32. 主キー/時刻の整数化設計と実装

Status: `pending`
Check: `none`

- `dataset_id` の整数キー化を設計する
- `observed_at` の整数時刻化を設計する
- 互換移行手順を実装する


### T33. 期間分割DB運用

Status: `pending`
Check: `none`

- 年単位などの分割方針を確定する
- CLI/GUIの対象DB切替手順を定義する
- 運用手順を文書化する


## 9. 実装順の推奨

推奨順序は以下とする。

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
23. T23
24. T24
25. T25
26. T26
27. T27
28. T28
29. T29
