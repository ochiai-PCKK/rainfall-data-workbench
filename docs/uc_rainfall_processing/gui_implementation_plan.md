# UC降雨処理 GUI 実装計画

## 1. 目的

本書は、[gui_design.md](C:/Users/yuuta.ochiai/Documents/28_jaxa_data/docs/uc_rainfall_processing/gui_design.md) を実装へ落とすための具体的な計画を定義する。

初期実装では、既存の CLI / サービス層を置き換えるのではなく、既存機能を呼び出す Tkinter フロントエンドを追加する。
また、GUI のテスト工程で AI エージェントが GUI を実際に操作し、状態・ログ・出力結果・画面表示を検証しやすいように、AI テストモードを追加する。


## 2. 現状確認

既存コードで GUI から再利用できるものは揃っている。

- 取り込み
  - `ingest_uc_rainfall()`
  - `ingest_uc_rainfall_many()`
- 候補セル取得
  - `list_candidate_cells()`
- グラフ出力
  - `generate_metric_event_charts()`
- 設定キャッシュ
  - `load_settings()`
  - `update_settings()`

また、現在のバックエンド挙動は GUI 要件と整合している。

- 入力は ZIP / 展開済みディレクトリの両対応
- 入力パスは複数指定可能
- `--polygon-dir` は任意
  - 未指定時は DB 内の polygon geometry を利用
- セル候補は流域内ローカル行列番号で選択可能
- グラフ出力時の `dataset_id` は任意
  - 未指定時は位置一致する全データセットを束ねる
  - 指定時は優先データセットとして扱う
- 設定キャッシュ `.uc_rainfall_settings.json` は既に存在する

AI GUI テストを入れるため、GUI 実装では以下を追加前提とする。

- GUI 現在状態のスナップショット出力
- ウィジェット一覧と状態の出力
- AI からの操作要求受付
- 操作結果とスクリーンショットの出力
- 直近実行結果の要約出力
- GUI ログの外部保存
- 画面主機能を圧迫しない補助的な配置


## 3. 実装方針

### 3.1 基本方針

- GUI は Tkinter で実装する
- 画面は単一ウィンドウとする
- 既存サービス層を直接呼び出す
- CLI のオプション体系をそのまま UI に露出せず、日本語の業務向けラベルへ変換する
- 設定キャッシュを使い、前回入力を復元する
- AI エージェントが参照できる機械可読な状態ファイルを生成する
- AI テストモードでは GUI を操作できるようにする
- ただし通常モードとテストモードは分離する
- テスト支援ボタンは補助配置とし、主ボタン群より目立たせすぎない
- AI が誤認しにくいように、主要 widget には安定した `widget_id` を付与する
- ラベルやボタン文言は重複を避け、1つの文言が1つの機能だけを指すようにする


### 3.2 日本語 UI 方針

内部識別子は保持するが、画面上は日本語に寄せる。

画面ラベルの第一候補:

- `DB パス` -> `データベース保存先`
- `入力パス` -> `取り込み対象`
- `polygon_dir` -> `流域ポリゴンフォルダ`
- `dataset_id` -> `取り込みID`
- `preferred dataset_id` -> `優先データセット`
- `series_mode=cell` -> `セル`
- `polygon_sum` -> `流域合計`
- `polygon_mean` -> `流域単純平均`
- `polygon_weighted_sum` -> `流域重み付き合計`
- `polygon_weighted_mean` -> `流域重み付き平均`

GUI 上では、英語の内部値を直接見せない。


## 4. 推奨ファイル構成

初期実装では GUI 用コードを `src/uc_rainfall/gui` にまとめる。

- `src/uc_rainfall/gui/__init__.py`
- `src/uc_rainfall/gui/app.py`
  - アプリ起動
  - ルートウィンドウ生成
  - 全体初期化
- `src/uc_rainfall/gui/state.py`
  - 画面状態
  - 入力値の読込 / 保存
  - `StringVar` などの束ね
- `src/uc_rainfall/gui/logging_handler.py`
  - logging を GUI のテキストエリアへ転送
- `src/uc_rainfall/gui/widgets.py`
  - 入力欄、候補セルテーブル、ログエリアなどの部品組立
- `src/uc_rainfall/gui/context_store.py`
  - GUI 状態の JSON 出力
  - ウィジェット一覧の JSON 出力
  - 操作要求 / 操作結果の読書き
  - 直近実行結果の JSON 出力
  - GUI ログの保存

必要に応じて、後から以下を分離する。

- `src/uc_rainfall/gui/actions.py`
  - ボタン押下時の処理
- `src/uc_rainfall/gui/validation.py`
  - 入力検証

初期実装では分割しすぎず、まずは `app.py + state.py + logging_handler.py + widgets.py + context_store.py` で十分。


## 5. 画面単位の実装範囲

### 5.1 入力エリア

実装対象:

- データベース保存先
- 取り込み対象一覧
  - ZIP / ディレクトリ複数選択
- 流域ポリゴンフォルダ
- 取り込みID
  - 単一入力時のみ有効
- 優先データセット
  - グラフ出力時のみ利用
- 流域名
- 系列
- 流域内行
- 流域内列
- 表示開始日時
- 表示終了日時
- 出力先フォルダ

ボタン:

- `DB初期化`
- `追加...`
- `選択解除`
- `取り込み`
- `候補セル一覧更新`
- `グラフ出力`
- `テスト状態を保存`
- `ウィジェット状態を保存`
- `画面を保存`
- `ログを保存`
- `テストモード切替`


### 5.2 候補セルエリア

`ttk.Treeview` を使う。

表示列:

- 流域名
- 流域内行
- 流域内列
- 中心X
- 中心Y
- 重なり率
- データセット数

行を選ぶと、`流域内行` と `流域内列` を入力欄へ反映する。


### 5.3 ログエリア

`tk.Text` または `ScrolledText` を使う。

表示内容:

- 取り込み開始 / 完了
- polygon 読込元
- 重複スキップ
- グラフ出力結果
- エラー要約

詳細な例外文字列はログエリアへ流し、ダイアログは短い日本語に留める。


### 5.4 テスト支援機能

実装対象:

- 現在状態サマリ表示
- 直近実行結果サマリ表示
- テスト状態保存ボタン
- ウィジェット状態保存ボタン
- 画面保存ボタン
- ログ保存ボタン

通常モードではここから業務処理を開始しない。
テストモードでは、AI 操作要求の処理結果もここに集約する。


## 6. 状態管理方針

### 6.1 設定キャッシュ

起動時に `.uc_rainfall_settings.json` を読み込む。

復元対象:

- `db_path`
- `polygon_dir`
- `input_paths`
- `polygon_name`
- `series_mode`
- `view_start`
- `view_end`
- `out_dir`
- `dataset_id`
- `preferred_dataset_id`

保存タイミング:

- DB 初期化成功時
- 取り込み成功時
- 候補セル一覧更新成功時
- グラフ出力成功時
- テスト状態保存時


### 6.2 GUI 内部状態

最低限持つ状態:

- 入力欄の `StringVar`
- 取り込み対象一覧
- 候補セル一覧 DataFrame 相当
- 実行中フラグ
- 現在状態サマリ
- 直近実行結果サマリ
- テストモード有効 / 無効
- widget 一覧キャッシュ
- 直近操作要求 / 操作結果

実行中は主要ボタンを無効化する。


## 7. イベント配線方針

### 7.1 DB 初期化

呼び出し:

- `initialize_schema()`

実装内容:

- DB パス検証
- 成功ログ
- 設定キャッシュ更新


### 7.2 取り込み

呼び出し:

- 入力 1 件
  - `ingest_uc_rainfall()`
- 入力 複数件
  - `ingest_uc_rainfall_many()`

実装内容:

- 入力件数で処理を分岐
- 取り込み中はボタン無効化
- 成功 / スキップ / 失敗をログへ出力
- 失敗時はメッセージボックス表示

注意点:

- 複数入力時は `取り込みID` を無効化する
- `流域ポリゴンフォルダ` が空でも、DB に polygon があれば実行可能


### 7.3 候補セル一覧更新

呼び出し:

- `list_candidate_cells(db_path=..., dataset_id=None or preferred_dataset_id, polygon_name=...)`

実装内容:

- 流域名必須
- 取得結果を `Treeview` へ再描画
- 0 件時は情報ダイアログ

判断:

- 既定では `dataset_id=None`
- GUI 上の `優先データセット` が入っている場合だけ絞り込みに使う


### 7.4 グラフ出力

呼び出し:

- `generate_metric_event_charts()`

実装内容:

- 系列モードが `セル` のときだけ流域内行列番号を必須化
- `dataset_id` は任意
- 出力後にファイル一覧をログへ出す


### 7.5 テスト状態保存

呼び出し:

- `save_gui_context()`

実装内容:

- 入力欄の現在値を `.uc_rainfall_gui_context.json` へ保存
- 候補セル一覧があれば要約も含める
- ログへ保存先を出力する


### 7.6 ウィジェット状態保存

呼び出し:

- `save_widget_tree()`

実装内容:

- widget 一覧を `.uc_rainfall_gui_widget_tree.json` へ保存
- 各 widget の `widget_id`, 種別, 表示名, 値, 有効状態, 位置, サイズを出力する


### 7.7 画面保存

呼び出し:

- 画面保存処理

実装内容:

- `.uc_rainfall_gui_last_screenshot.png` を更新する
- AI が視覚確認できる状態にする


### 7.8 直近実行結果保存

呼び出し:

- 実行結果保存処理

実装内容:

- `.uc_rainfall_gui_last_run.json` を更新する
- 出力ファイル一覧やエラー要約を保存する
- 画面上のサマリも更新する


### 7.9 ログ保存

呼び出し:

- ログ保存処理

実装内容:

- `.uc_rainfall_gui_log.txt` を出力する
- GUI のログ表示内容を外部確認できるようにする


### 7.10 テストモード操作要求処理

呼び出し:

- `process_action_request()`

実装内容:

- `.uc_rainfall_gui_action_request.json` を読み込む
- 対象 `widget_id` と操作種別を解決する
- `click`, `set_text`, `select`, `invoke`, `focus` などの最小操作を実行する
- 結果を `.uc_rainfall_gui_action_result.json` へ保存する
- 実行後に context, widget tree, screenshot, log を更新する


## 8. 実装順

### フェーズ1: GUI 骨格

目的:

- ウィンドウが開く
- 入力欄が並ぶ
- 設定キャッシュを読める

作業:

- `gui/app.py` 作成
- `gui/state.py` 作成
- `gui/context_store.py` 作成
- 入力エリアの基本レイアウト作成
- 設定読込 / 初期反映


### フェーズ2: 取り込み操作

目的:

- DB 初期化
- 入力パス追加 / 削除
- 取り込み実行

作業:

- ファイル選択ダイアログ
- 複数入力リスト
- 入力件数に応じた `取り込みID` の有効 / 無効制御
- `ingest_uc_rainfall()` / `ingest_uc_rainfall_many()` 配線


### フェーズ3: 候補セル一覧

目的:

- 流域名に応じて候補セルが見える
- 行選択で `流域内行 / 流域内列` が入る

作業:

- `Treeview` 実装
- 候補セル取得ボタン実装
- 行選択イベント実装


### フェーズ4: AI テストモード

目的:

- AI が GUI を操作できる
- 実行後の状態と画面を AI が検証できる

作業:

- `.uc_rainfall_gui_context.json` 出力
- `.uc_rainfall_gui_widget_tree.json` 出力
- `.uc_rainfall_gui_action_request.json` 読込
- `.uc_rainfall_gui_action_result.json` 出力
- `.uc_rainfall_gui_last_screenshot.png` 出力
- `.uc_rainfall_gui_last_run.json` 出力
- `.uc_rainfall_gui_log.txt` 保存
- テスト用サマリ表示


### フェーズ5: グラフ出力

目的:

- セル単位 / 流域集計のグラフを GUI から出せる

作業:

- 系列モードのコンボボックス
- セルモード時の行列入力制御
- `generate_metric_event_charts()` 配線
- 出力結果ログ表示


### フェーズ6: ログ・応答性

目的:

- 実行状況が分かる
- UI が固まって見えにくくならない

作業:

- GUI 向け logging handler 実装
- 実行中フラグとボタン制御
- 可能なら `after()` ベースの軽い非同期化


## 9. バリデーション実装方針

最初に入れるべき検証:

- データベース保存先が空でない
- 取り込み時は入力対象が 1 件以上
- `セル` モード時は流域内行 / 流域内列が整数
- グラフ出力時は流域名が空でない
- 表示開始 <= 表示終了
- 出力先フォルダが空でない
- テスト状態保存先とログ保存先は書き込み可能である
- テストモード操作では未知の `widget_id` を拒否する
- テストモード操作では GUI 対象外の危険操作を拒否する

エラーメッセージは短い日本語にする。

例:

- `データベース保存先を指定してください。`
- `取り込み対象を1件以上選択してください。`
- `セルモードでは流域内行と流域内列を指定してください。`


## 10. 検証計画

### 10.1 最低限の動作確認

1. 前回 DB パスが起動時に復元される
2. 複数 ZIP を選択して取り込める
3. polygon_dir 未指定でも DB polygon から取り込める
4. 流域名を指定して候補セル一覧が見える
5. 候補セル選択で流域内行 / 列が入る
6. `セル` モードでグラフ出力できる
7. `流域重み付き平均` モードでグラフ出力できる
8. 現在状態を JSON として保存できる
9. ウィジェット状態を JSON として保存できる
10. テストモードで `click` や `set_text` を実行できる
11. 実行後スクリーンショットを保存できる
12. GUI ログをテキストとして保存できる


### 10.2 実データ確認

確認対象 DB:

- `outputs/uc_data_zip_trim.sqlite3`

確認対象入力:

- `data/uc_data_zip` 内の複数 ZIP

確認対象流域:

- `大和川流域界`
- `東除川流域`
- `西除川流域`
- `東除川流域 + 西除川流域`


## 11. 初期実装でやらないこと

- 地図プレビュー
- グラフ画像プレビュー
- バックグラウンドスレッドの本格実装
- PDF 出力
- 複数グラフの一括サムネイル表示
- AI エージェントによる本番モードでの GUI 自動操作


## 12. 次アクション

GUI 実装は以下の順で着手する。

1. `src/uc_rainfall/gui` パッケージ追加
2. ルートウィンドウと入力エリア作成
3. 設定キャッシュ復元
4. 取り込み機能配線
5. 候補セルテーブル配線
6. テスト支援ファイルの出力配線
7. AI テストモードの操作要求処理配線
8. グラフ出力配線
9. ログ転送と細部調整


## 13. 面的可視化ビューの次段階

面的可視化ビューの詳細は [spatial_view_design.md](C:/Users/yuuta.ochiai/Documents/28_jaxa_data/docs/uc_rainfall_processing/spatial_view_design.md) を参照する。

GUI 実装の次段階では、以下を追加する。

1. 面ビュー用サービス層追加
2. `面ビュー` タブ追加
3. 単一時刻ヒートマップ
4. 累加雨量ヒートマップ
5. セルクリック選択
6. AI テストモードの `canvas` 操作
