# UC降雨処理 タスク分解

## 1. 方針

タスクは、依存関係が明確になるようにフェーズ1、フェーズ2、検証、将来拡張準備に分けて進める。

初期実装では、以下をゴールとする。

- UC-tools データを DB へ取り込める
- 流域ごとの候補セルを抽出できる
- CLI で候補セルを確認できる
- `row/col` 指定で対象セルを選べる
- 指定期間内の各指標最大イベントグラフを出力できる


## 2. フェーズ1: 取り込み・DB格納

### T1. プロジェクト骨組み作成

- `src/uc_rainfall` 配下のモジュール構成を作成する
- `cli.py`, `db.py`, `schema.py`, `models.py` の雛形を作る
- `ingest`, `spatial`, `graph`, `services` パッケージを作る


### T2. DB スキーマ実装

- SQLite 接続処理を実装する
- `datasets`, `grids`, `cell_timeseries`, `polygons`, `polygon_cell_map` の DDL を実装する
- 初期化処理を CLI から呼べるようにする
- 必要インデックスを作成する


### T3. UC-tools 入力ローダ実装

- 入力ディレクトリ存在確認を実装する
- ZIP ファイル入力を受けて一時展開する処理を実装する
- `rain.dat`、ラスタ群、メール本文の探索処理を実装する
- 必要ファイル一覧を返すローダを作る


### T4. 時刻復元実装

- TIFF 名から `_JST_YYYYMMDD_HHMMSS` を抽出する処理を実装する
- UTC 相当ファイル名から JST へ変換する補助処理を実装する
- `rain.dat` 経過秒を解釈する補助処理を実装する
- 時刻列確定ロジックを実装する
- `rain.dat` ブロック数との整合確認を実装する


### T5. rain.dat パーサ実装

- ブロック単位で `elapsed_seconds rows cols` を読む処理を実装する
- 値本体を `row/col` 単位へ展開する処理を実装する
- 格子サイズの整合確認を実装する


### T6. 格子定義・セル中心座標計算実装

- 基準座標、セル幅、セル高、行数、列数を扱うモデルを作る
- `mail_txt.txt` がない場合に TIFF から格子定義を取得する処理を実装する
- `row/col -> x_center/y_center` 変換処理を実装する
- `cell_timeseries` 用のレコード生成処理を作る


### T7. フェーズ1保存処理実装

- `datasets` への保存処理を実装する
- `grids` への保存処理を実装する
- `cell_timeseries` への一括保存処理を実装する


### T7a. 重複登録判定実装

- 同一格子定義を持つ既存 `dataset_id` を特定する
- 完全一致データセットをスキップする処理を実装する
- 重複時刻で値不一致ならエラーにする処理を実装する
- 判定結果をログ出力する


## 3. フェーズ1: 空間対応付け

### T8. ポリゴンローダ実装

- 流域ポリゴンファイルの読込処理を実装する
- 対象4領域の管理処理を実装する
- `polygon_id`, `polygon_name`, `bbox`, `crs` を抽出する


### T9. polygons 保存処理実装

- `polygons` テーブルへの保存処理を実装する
- 重複登録時の更新方針を決めて実装する


### T10. 候補セル抽出実装

- セルポリゴン BBox と流域 BBox の重なりで候補を絞る処理を実装する
- セルポリゴンと流域ポリゴンの `intersects` 判定を実装する
- `cell_intersects_polygon` 方式で採用セルを決定する


### T11. polygon_cell_map 保存処理実装

- `polygon_cell_map` への保存処理を実装する
- `dataset_id + polygon_id + row + col` の一意性を守る
- `polygon_local_row`, `polygon_local_col` を算出して保存する
- `cell_area`, `overlap_area`, `overlap_ratio` を算出して保存する


### T12. ingest サービス統合

- フェーズ1全体を `ingest_service.py` で統合する
- `ingest` CLI コマンドから実行できるようにする
- ログ出力を整える


## 4. フェーズ2: 候補セル参照

### T13. 候補セル一覧取得実装

- `polygon_cell_map` と `cell_timeseries` を使って候補セル一覧を取得する
- `polygon_name`, `row`, `col`, `x_center`, `y_center`, `inside_flag` を返す


### T14. CLI 候補ビュー実装

- `list-cells` コマンドを実装する
- 一覧形式で候補セルを表示する
- 並び順を `polygon_name`, `row`, `col` にそろえる
- `polygon_local_row`, `polygon_local_col` も表示する


## 5. フェーズ2: グラフ生成

### T15. 時系列取得実装

- `dataset_id + row + col` でセル時系列を取得する
- `dataset_id + polygon_local_row + polygon_local_col` でも起点セルを解決できるようにする
- 同一格子定義を持つ複数 `dataset_id` を特定する
- 可視化時に同一格子の `dataset_id` を結合して時系列を作る
- セル単位では `x_center/y_center` 一致セルだけを結合する
- `view_start`, `view_end` を受け取る
- `calc_start` を内部計算して必要期間を読み出す
- `polygon_sum`, `polygon_mean`, `polygon_weighted_sum`, `polygon_weighted_mean` の流域集計時系列を取得できるようにする


### T16. rolling 指標計算実装

- 1h, 3h, 6h, 12h, 24h, 48h を計算する処理を実装する
- trailing rolling sum を採用する
- `min_periods = window` を守る
- 欠測を 0 補完しない


### T17. 最大イベント抽出実装

- 指標ごとの最大値を求める
- 同値最大時は最初の発生時刻を採用する
- 他の同値候補時刻をログ出力する


### T18. イベント切り出し実装

- 指標ごとの表示幅設定を実装する
- 参考実装準拠の切り出し幅を定数化する
- 発生時刻前後の表示期間を切り出す


### T19. グラフ描画実装

- 1時間雨量棒グラフを描画する
- 指標別累加雨量折れ線を描画する
- 軸ラベル、タイトル、凡例を実装する
- PNG 出力処理を実装する


### T20. ファイル命名実装

- `{dataset_id}_{polygon_name}_r{row}_c{col}_{metric}_{event_time_jst}.png` を実装する
- ファイル名安全化処理を入れる


### T21. plot サービス統合

- フェーズ2全体を `graph_service.py` で統合する
- `plot` CLI コマンドから実行できるようにする


## 6. 検証

### T22. フェーズ1動作確認

- 実データで DB 作成が通ることを確認する
- `datasets`, `grids`, `cell_timeseries`, `polygons`, `polygon_cell_map` に想定件数が入ることを確認する


### T23. 候補ビュー確認

- `list-cells` で候補セル一覧が見えることを確認する
- `row/col` と `x_center/y_center` が妥当であることを確認する


### T24. グラフ出力確認

- 1セルを選び、6指標分の PNG が出ることを確認する
- 同値最大時ログが出ることを確認する
- 期間指定が反映されることを確認する


### T25. 境界ケース確認

- 候補セルゼロ
- 指定 `row/col` 不正
- 指定期間にデータなし
- 48時間未満のデータ
- 欠測を含むデータ
- 同一格子で複数 `dataset_id` が存在するケース
- 同一 `observed_at` が重複するケース


## 7. ドキュメント・仕上げ

### T26. README 追記

- セットアップ方法
- DB 初期化方法
- `ingest`, `list-cells`, `plot` の使用例


### T27. 設計との差分反映

- 実装途中で変更した仕様を `requirements.md`, `design.md`, `detail_design.md` に反映する


## 8. 実装順の推奨

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
