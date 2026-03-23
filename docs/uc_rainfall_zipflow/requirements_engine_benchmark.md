# UC Rainfall ZIP Flow エンジン切替ベンチマーク 要件定義

## 1. 目的

本書は、既存Python実装と将来のRust実装を切り替えて性能比較するための要件を定義する。  
目的は「移行可否を感覚ではなく数値で判断する」こととする。

## 2. スコープ

### 2.1 対象

- 計算エンジン切替（`python` / `rust`）
- 同一入力でのベンチマーク実行
- 性能・精度・安定性のスコア算出
- ベンチ結果の保存（JSON/CSV）

### 2.2 対象外

- Rust全面移植
- GUI全体の性能測定
- GPU最適化

## 3. 比較対象機能

- 最優先比較対象は重み付き集計コアとする
  - `weighted_sum`
  - `weighted_mean`
  - `coverage_ratio`
- 必要に応じて段階的に比較範囲を拡張する
  - Phase 1: 集計コアのみ
  - Phase 2: クリップ + 集計
  - Phase 3: 期間窓切出し + グラフ前処理

## 4. 機能要件

### 4.1 エンジン切替

- CLIに `--engine {python|rust}` を追加する
- 既定値は `python` とする
- `rust` 未実装時は明示メッセージで失敗させる（サイレントフォールバック禁止）

### 4.2 ベンチ実行

- CLIに `benchmark` サブコマンドを追加する
- 同一入力に対して `python` と `rust` を連続実行する
- 各実行を最低3回実施し、中央値を採用する
- ウォームアップ1回を計測対象外として実施する

### 4.3 計測項目

- 必須
  - `wall_time_ms`
  - `cpu_time_ms`
  - `peak_rss_mb`
  - `output_rows`
  - `max_abs_diff`
  - `rmse`
- 任意
  - `io_read_mb`
  - `io_write_mb`

### 4.4 スコア算出

- 速度スコア: `speed_score = python_wall_ms / rust_wall_ms`
- メモリスコア: `memory_score = python_peak_rss_mb / rust_peak_rss_mb`
- 精度ペナルティ
  - `max_abs_diff > 1e-6` または `rmse > 1e-7` の場合は失格
- 総合スコア（精度合格時のみ）
  - `total_score = 0.7 * speed_score + 0.3 * memory_score`

### 4.5 結果出力

- `outputs/uc_rainfall_zipflow/benchmarks/{timestamp}/` 配下に保存する
- 出力ファイル
  - `summary.json`
  - `runs.csv`
  - `score.json`
- 実行条件（入力パス、期間、地域、CPU情報、Python/Rustバージョン）を必須記録する

## 5. 非機能要件

- 再現性
  - 同一入力・同一環境で結果差が一定範囲に収まること
- 可観測性
  - 失敗時にどのエンジン・どのステップで失敗したか分かること
- 拡張性
  - 将来 `cpp` など第三エンジンを追加できる構造にすること

## 6. 受け入れ条件

- `benchmark` コマンドで `python` / `rust` 両方の結果が出る
- 速度・メモリ・精度・総合スコアが保存される
- 精度閾値違反時に失格判定される
- 既存 `run` コマンド利用時の挙動に退行がない

## 7. リスクと対策

- リスク: 入力差分で比較が無効になる
  - 対策: ベンチ専用固定データセットを使用する
- リスク: Rust実装未完成で比較不能
  - 対策: `python` vs `python_stub` 比較を先に整備し計測基盤を先行完成させる
- リスク: 計測ノイズ
  - 対策: 複数回実行・中央値採用・ウォームアップ実施

## 8. 設計

### 8.1 アーキテクチャ

- `engine` 抽象を導入し、計算コア呼び出しを統一する
- `python` 実装は既存関数をラップする
- `rust` 実装は外部プロセス（CLI）呼び出しで接続する
- `benchmark` 実行器は `engine` を差し替えて同一シナリオを実行する

### 8.2 モジュール構成（追加）

- `src/uc_rainfall_zipflow/engine/interface.py`
  - `EngineRunner` プロトコル定義
- `src/uc_rainfall_zipflow/engine/python_engine.py`
  - 既存ロジック呼び出し
- `src/uc_rainfall_zipflow/engine/rust_engine.py`
  - Rust CLI呼び出し
- `src/uc_rainfall_zipflow/benchmark/runner.py`
  - ウォームアップ、反復実行、中央値算出
- `src/uc_rainfall_zipflow/benchmark/scoring.py`
  - 差分計算、スコア計算、合否判定
- `src/uc_rainfall_zipflow/benchmark/report.py`
  - JSON/CSV出力

### 8.3 データ契約

- 入力契約（最小）
  - `observed_at[]`
  - `weights[]`
  - `values[]`
  - `region_key`
  - `slot_index`
- 出力契約（最小）
  - `weighted_sum_mm[]`
  - `weighted_mean_mm[]`
  - `coverage_ratio[]`

### 8.4 CLI設計

- 既存 `run` に `--engine` を追加
- 新規 `benchmark` を追加
  - 例:
    - `uv run python -m uc_rainfall_zipflow.cli benchmark --scenario core_weighted --repeat 5 --warmup 1`
    - `uv run python -m uc_rainfall_zipflow.cli run --engine rust ...`

### 8.5 Rust接続方式

- 初期は「標準入出力JSON」方式を採用する
  - Python -> Rust: JSON入力をstdinで渡す
  - Rust -> Python: JSON結果をstdoutで返す
- エラー時は非0終了コード + stderrメッセージを返す

### 8.6 計測詳細

- 時間計測
  - `wall_time_ms`: Python側で実測
  - `cpu_time_ms`: Python側でプロセスCPU時間を取得
- メモリ計測
  - Pythonエンジン: `psutil` でピークRSS
  - Rustエンジン: サブプロセス監視でピークRSS
- 精度比較
  - 同一インデックスで `weighted_sum_mm`, `weighted_mean_mm`, `coverage_ratio` を比較
  - ずれがある場合、最大差分行を `summary.json` に記録

### 8.7 出力フォーマット

- `summary.json`
  - `scenario`
  - `repeat`
  - `warmup`
  - `python_median`
  - `rust_median`
  - `speed_score`
  - `memory_score`
  - `total_score`
  - `accuracy_passed`
- `runs.csv`
  - `engine,run_no,wall_time_ms,cpu_time_ms,peak_rss_mb,output_rows,max_abs_diff,rmse`
- `score.json`
  - スコア計算式と各入力値を保存

### 8.8 失敗時挙動

- `rust` 実行ファイルが無い場合
  - `benchmark`: `rust` を `not_available` として記録し終了コード`2`
  - `run --engine rust`: 明示エラーで終了
- 精度閾値違反
  - `benchmark` は終了コード`3`で失敗

### 8.9 テスト設計

- 単体
  - スコア計算式
  - 精度閾値判定
  - レポート出力
- 結合
  - `benchmark` で両エンジン呼び出し
  - `--engine` 切替で `run` が正しい実装を選ぶ
- 疎通
  - Rust CLIの最低限I/O（stdin JSON -> stdout JSON）

## 9. タスク分解

## 9.1 フェーズA: 基盤

### A1. `engine` 抽象導入

- 内容
  - `EngineRunner` インターフェース追加
  - 既存計算呼び出しを `python_engine` に移設
- 完了条件
  - `run` で `--engine python` が従来結果と一致

### A2. `--engine` CLI配線

- 内容
  - `run` サブコマンドに `--engine` 追加
  - `python|rust` バリデーション
- 完了条件
  - 不正値でエラー、既定値`python`確認

## 9.2 フェーズB: ベンチ実行

### B1. `benchmark` サブコマンド追加

- 内容
  - 引数: `--scenario`, `--repeat`, `--warmup`, `--output-dir`
  - シナリオ読み込みと実行器呼び出し
- 完了条件
  - Python単独でベンチ結果が保存される

### B2. 計測機構実装

- 内容
  - wall/cpu/peak_rss 取得
  - 反復実行 + 中央値算出
- 完了条件
  - `runs.csv` と `summary.json` に値が出る

### B3. スコア実装

- 内容
  - speed/memory/total 計算
  - 精度閾値判定
- 完了条件
  - `score.json` が生成される

## 9.3 フェーズC: Rust接続

### C1. Rust CLIひな形作成

- 内容
  - `crates/weighted_core` 作成
  - JSON入出力のみ実装（計算はPython互換）
- 完了条件
  - サンプル入力でstdout JSONを返す

### C2. Python-Rustブリッジ実装

- 内容
  - `rust_engine.py` でサブプロセス呼び出し
  - タイムアウト・stderr・終了コード処理
- 完了条件
  - `--engine rust` の疎通確認

### C3. 精度比較の実装

- 内容
  - Python結果とRust結果を列単位比較
  - `max_abs_diff` / `rmse` 算出
- 完了条件
  - 差分がレポートに反映される

## 9.4 フェーズD: 検証

### D1. 固定ベンチデータセット整備

- 内容
  - 小/中/大の3シナリオデータ作成
  - データバージョン管理
- 完了条件
  - CI/ローカルで同一入力が再利用できる

### D2. 回帰テスト追加

- 内容
  - engine切替回帰
  - benchmark出力回帰
- 完了条件
  - `pytest` に統合される

### D3. 受入判定運用

- 内容
  - 目標値設定（例: `total_score >= 1.2`）
  - 判定ログを保存
- 完了条件
  - 実行ごとに採用可否が判定される

## 10. 実装順序（推奨）

1. A1
2. A2
3. B1
4. B2
5. B3
6. C1
7. C2
8. C3
9. D1
10. D2
11. D3
