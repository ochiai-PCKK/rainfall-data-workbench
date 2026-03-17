# UC ダウンロード自動化 タスク分解

## 1. 方針

タスクは、まずフェーズ 1 の要求送信機能を完了扱いで維持し、その後に新仕様としてメール本文取り込みと ZIP 保存を接続する順序で進める。

本書では、以下の前提で状態を管理する。

- フェーズ 1: 要求送信機能は実装済みであり、原則 `done` 扱いとする
- フェーズ 2 以降: メール本文の手動貼り付け取り込みと ZIP 保存は新仕様として追加する

全体ゴールは以下とする。

- `src/uc_download` を新規追加できる
- ログインページから OTP 待機までを扱える
- 大和川流域 bbox と 3 日単位期間で単発要求を送れる
- `確認画面` と `変換開始` を通過できる
- `2010-01-02` から `2025-12-31` までの期間窓を生成できる
- 同一ブラウザセッションで複数期間を連続送信できる
- 貼り付けたメール本文から URL と期間を抽出できる
- 期間の連続性、重複、欠落を判定できる
- 保存済み URL から ZIP を取得し manifest へ反映できる


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

前段で完了済みのタスクに、後段仕様の観点で未実装項目が増えた場合でも、その未実装項目が別フェーズの責務であれば前段タスクは `done` のままとする。

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


## 2. フェーズ1: 骨組み作成

### T1. パッケージ雛形作成

Status: `done`
Check: `code`

- `src/uc_download` パッケージを作成する
- `__init__.py`, `cli.py`, `config.py`, `models.py` の雛形を作る
- `pages`, `workflows` サブパッケージを作る
- 後段用に `mail_parser.py`, `continuity_checker.py`, `download_store.py`, `zip_downloader.py` の配置先を決める


### T2. 設定定義実装

Status: `done`
Check: `code`

- ログイン URL、パラメータ URL を定義する
- 既定メールアドレスを定義する
- 大和川流域 bbox プリセットと余白既定値を定義する
- 期間既定値 `2010-01-02` から `2025-12-31` を定義する
- メール本文保存先と ZIP 保存先の既定値を定義する
Note: 前段で必要な設定は実装済み。メール本文保存先と ZIP 保存先は後段フェーズで追加する。


### T3. selector 定義実装

Status: `done`
Check: `code`

- ログインページ selector を定義する
- パラメータ画面 selector を定義する
- 確認画面 selector を定義する
- `OK` 検知候補 selector を定義する


## 3. フェーズ2: 基盤処理

### T4. データモデル実装

Status: `done`
Check: `code`

- `BBox` を実装する
- `RequestWindow` を実装する
- `RunConfig` を実装する
- `RequestResult` を実装する
  - `accepted`
  - `accepted_candidate`
  - `failed` を区別できるようにする
- `MailEntry` を実装する
- `ContinuityIssue` を実装する
- `ZipDownloadResult` を実装する
Note: `BBox`, `RequestWindow`, `RunConfig`, `RequestResult` は実装済み。後段モデルは別フェーズで追加する。


### T5. 期間分割実装

Status: `done`
Check: `code`, `manual`

- `period_planner.py` を実装する
- 3 日単位の要求窓生成を実装する
- 末尾 1 日または 2 日のケースを実装する
- 1948 件になることを確認できるようにする


### T6. 結果保存実装

Status: `done`
Check: `code`, `manual`

- 実行設定 JSON 保存を実装する
- 要求結果 JSON 保存を実装する
- 実行サマリ保存を実装する
- スクリーンショット保存パス管理を実装する
- raw メール本文保存を実装する
- `mail_entries.json` 保存を実装する
- `continuity_issues.json` 保存を実装する
- `download_manifest.json` 保存を実装する
Note: `run_config.json`, `request_results.json`, `run_summary.json`, `screenshots` は実装済み。メール本文系保存は後段フェーズで追加する。


### T7. ブラウザ起動実装

Status: `done`
Check: `code`

- Chromium 起動処理を実装する
- headed 実行を既定にする
- viewport と timeout を設定する
- 1 browser / 1 context / 1 page の扱いをまとめる


## 4. フェーズ3: ページオブジェクト

### T8. ログインページ実装

Status: `done`
Check: `code`

- ログインページを開く処理を実装する
- メールアドレス入力を実装する
- `ログイン` 押下を実装する
- ログインページ存在確認を実装する


### T9. パラメータ画面実装

Status: `done`
Check: `code`

- パラメータ画面 ready 判定を実装する
- 開始日設定を実装する
- 日数設定を実装する
- bbox 直接設定を実装する
- `確認画面` 押下と popup 取得を実装する


### T10. 確認画面実装

Status: `done`
Check: `code`

- 確認画面 ready 判定を実装する
- `変換開始` 押下を実装する
- `OK` / `dialog` / タブ閉鎖の検知を実装する
- 正常完了候補の判定を実装する


## 5. フェーズ4: 単発ワークフロー

### T11. ログインワークフロー実装

Status: `done`
Check: `code`

- ログインページを開く
- メールアドレスを入力する
- `ログイン` を押す
- OTP 完了後のパラメータ画面待機を実装する


### T12. 単発要求ワークフロー実装

Status: `done`
Check: `code`, `manual`

- 開始日、日数、bbox を設定する
- パラメータ画面のスクリーンショットを保存する
- `確認画面` popup を取得する
- 確認画面のスクリーンショットを保存する
- `変換開始` 後の `accepted` / `accepted_candidate` 判定を返す


### T13. 単発 CLI 実装

Status: `done`
Check: `code`, `manual`

- `plan-periods` を実装する
- `login-and-request` を実装する
- 実行結果ファイル出力を配線する


## 6. フェーズ5: 連続送信

### T14. 連続送信ループ実装

Status: `done`
Check: `code`, `manual`

- `RequestWindow` 一覧を順に処理するループを実装する
- 各要求後に結果を逐次保存する
- 次の期間へ進む処理を実装する
- 停止時に直前成功期間と失敗期間を保存する


### T15. 連続送信後の画面復帰処理実装

Status: `done`
Check: `code`, `manual`

- `確認画面` popup 終了後に元画面が継続利用可能か確認する
- 次期間設定前の画面安定待機を実装する
- 連続送信時の race condition を抑える待機を実装する


### T16. 連続送信 CLI 実装

Status: `done`
Check: `code`, `manual`

- `loop-request-links` を実装する
- 開始期間、終了期間、chunk 日数を外部指定できるようにする
- 既定値で全期間を回せるようにする


## 7. フェーズ6: メール本文取り込み

### T17. メール本文 parser 実装

Status: `done`
Check: `code`, `manual`

- 1 件のメール本文から URL を抽出する
- 1 件のメール本文からデータ期間を抽出する
- 複数件連結された本文をメール単位に分割する
- 抽出失敗時に理由を返す


### T18. 期間整合性チェック実装

Status: `done`
Check: `code`, `manual`

- `MailEntry` 一覧を開始日順に並べる
- gap を検出する
- overlap を検出する
- duplicate を検出する
- 想定期間外データを検出する


### T19. メール本文取り込みワークフロー実装

Status: `done`
Check: `code`, `manual`

- 入力テキストを受け取る
- raw 本文を保存する
- 構造化済み `MailEntry` を保存する
- 既存データを含めて整合性チェックを行う
- issue 一覧を保存する
- 成功件数、失敗件数、警告件数を返す


### T20. メール本文取り込み CLI 実装

Status: `done`
Check: `code`, `manual`

- `ingest-mail-bodies` を実装する
- ファイル入力と標準入力を受け付ける
- warning あり終了を通常成功と区別できるようにする
- 警告件数を CLI 出力で確認できるようにする


## 8. フェーズ7: ZIP 取得

### T21. ZIP ダウンロード実装

Status: `done`
Check: `code`, `manual`

- URL に対して HTTP リクエストを送る
- ZIP 応答を保存する
- 空ファイルや異常応答を検出する
- 既存 ZIP の再取得回避を実装する


### T22. ZIP 取得ワークフロー実装

Status: `done`
Check: `code`, `manual`

- 未取得または再取得対象のエントリを列挙する
- 1 件ずつダウンロードする
- 成功、失敗、既取得再利用を記録する
- 統合 manifest を更新する


### T23. ZIP 取得 CLI 実装

Status: `done`
Check: `code`, `manual`

- `fetch-zips` を実装する
- 対象 status を絞って実行できるようにする
- 全件処理後のサマリを出力する
- `failed` / `expired` の代表例を CLI で確認できるようにする


### T23a. 簡易 GUI 実装

Status: `done`
Check: `code`, `manual`

- `launch-gui` を実装する
- メール本文貼り付け欄を表示する
- `取り込み` と `ZIP取得` を GUI から実行できるようにする
- クリップボード貼付とショートカットキーを実装する
- クリップボード監視による自動取り込みと自動 ZIP 取得を実装する


## 9. フェーズ8: 検証

### T24. 単発要求検証

Status: `partial`
Check: `manual`

- ログインから単発要求まで通ることを確認する
- `確認画面` popup が捕捉できることを確認する
- `変換開始` 後に受理シグナルが取れることを確認する
- メールリンクが到着することを確認する


### T25. 連続送信検証

Status: `partial`
Check: `manual`

- 同一セッションで 2 件連続送信を確認する
- 同一セッションで 3 件以上送信を確認する
- `accepted_candidate` が連続した場合でも元画面へ戻れることを確認する
- 期間進行が正しいことを確認する


### T26. メール本文取り込み検証

Status: `done`
Check: `manual`

- サンプル本文から URL と期間が抽出できることを確認する
- 期間の連続性が正しく判定されることを確認する
- 重複と欠落が警告されることを確認する
- 抽出失敗本文が raw text として残ることを確認する


### T27. ZIP 取得検証

Status: `done`
Check: `manual`

- 保存済み URL から ZIP を取得できることを確認する
- ZIP と期間の対応が manifest に残ることを確認する
- 既取得 ZIP を再実行時に再利用できることを確認する


### T28. 失敗ケース検証

Status: `partial`
Check: `manual`

- OTP 待機タイムアウト
- パラメータ画面未到達
- `確認画面` popup 未生成
- `変換開始` 後に受理シグナルが取れない
- セッション切れ
- メール本文から URL または期間を抽出できない
- 期間整合性が崩れている
- ZIP URL が期限切れで取得できない
Note: `ZIP URL が期限切れで取得できない` は 404 応答を使った基本確認まで実施済み。非 ZIP の HTML 応答では `failed` とレスポンス先頭保存まで確認済み。前段ブラウザ系の失敗ケースは未確認。


### T29. 実行結果検証

Status: `done`
Check: `manual`

- `request_results.json` が `accepted` と `accepted_candidate` を持つことを確認する
- 失敗時にも最後の期間が残ることを確認する
- スクリーンショットが適切に保存されることを確認する
- `mail_entries.json` が URL と期間を持つことを確認する
- `download_manifest.json` が request / mail / zip の状態を横断して持つことを確認する
Note: `mail_entries.json`, `continuity_issues.json`, `zip_results.json`, `download_manifest.json` を確認済み。


## 10. ドキュメント・仕上げ

### T30. 設計との差分反映

Status: `done`
Check: `docs`

- 実装差分を `requirements.md` に反映する
- 実装差分を `detail_design.md` に反映する
- 実験結果に追記が必要なら `experiment_results.md` を更新する


### T31. 利用手順整理

Status: `done`
Check: `docs`

- セットアップ手順を整理する
- `login-and-request` の実行例を整理する
- `loop-request-links` の実行例を整理する
- `ingest-mail-bodies` の実行例を整理する
- `fetch-zips` の実行例を整理する
- 実行結果ファイルの見方を整理する
Note: `ingest-mail-bodies` と `fetch-zips` の実行例まで反映済み。


## 11. 実装順の推奨

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
30. T30
31. T31
