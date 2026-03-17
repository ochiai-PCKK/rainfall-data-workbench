# UC ダウンロード自動化 利用手順

## 1. 目的

本書は、`src/uc_download` に実装した既存機能の使い方と、今後追加する拡張予定の境界をまとめる。

現時点で実装済みの対象は、ログインページから開始し、人手で OTP を入力した後、解析雨量のダウンロードリンク送信要求を自動で実行するところまでである。

メール本文の貼り付け取り込みと ZIP の実ダウンロードは実装済みである。`uc_rainfall` への取り込みは、現時点では未実装の拡張予定である。


## 2. 前提

利用前提は以下である。

- Python 環境は `uv` で利用できること
- `playwright` が依存として導入済みであること
- Chromium が `playwright install chromium` 済みであること
- OTP は人手で入力すること
- ブラウザを途中で閉じないこと

本機能は、同一ブラウザセッションの継続を前提としている。
ブラウザを閉じるとセッション再利用が成立しない可能性が高いため、OTP 完了後もそのまま同じブラウザを使う。


## 3. 既定値

現時点の実装で使う既定値は以下である。

- ログイン URL: `https://tools.i-ric.info/login/`
- パラメータ画面 URL: `https://tools.i-ric.info/confirm/`
- メールアドレス: `yuuta.ochiai@tk.pacific.co.jp`
- bbox プリセット: `yamatogawa`
- bbox 余白: `0.02` 度
- 期間開始: `2010-01-02`
- 期間終了: `2025-12-31`
- 分割日数: `3`

大和川流域で実際に使う bbox は以下である。

- `south=34.31633333`
- `north=34.80113889`
- `west=135.41291667`
- `east=135.96752778`


## 4. セットアップ

依存同期:

```powershell
uv sync
```

Playwright Chromium 導入:

```powershell
uv run playwright install chromium
```

CLI ヘルプ確認:

```powershell
uv run python -m uc_download.cli --help
```


## 5. 期間計画の生成

全期間を 3 日単位へ分割して確認したい場合:

```powershell
uv run python -m uc_download.cli plan-periods
```

結果は `outputs/uc_download/period_plan.json` に保存される。

この既定設定では、要求件数は `1948` 件である。


## 6. 単発実行

1 期間だけ要求送信を行いたい場合:

```powershell
uv run python -m uc_download.cli login-and-request --start-day 2025-01-01 --days 3
```

実行の流れは以下である。

1. ブラウザが開く
2. ログインページでメールアドレスが入力され、`ログイン` が押される
3. OTP 入力待機になる
4. 利用者が OTP を入力してログインを完了する
5. パラメータ画面が出たら、開始日、日数、bbox が自動で設定される
6. パラメータ画面に表示された bbox が期待値と一致するか確認される
7. `確認画面` の別タブが開く
8. 確認画面に表示された bbox が期待値と一致するか確認される
9. `変換開始` が押される
10. 要求結果が `outputs/uc_download` に保存される


## 7. 全期間実行

全期間へ要求送信を繰り返したい場合:

```powershell
uv run python -m uc_download.cli loop-request-links
```

このコマンドは以下の既定条件で動作する。

- 期間: `2010-01-02` から `2025-12-31`
- 日数: 3 日単位
- bbox: `yamatogawa` + `0.02` 度余白

必要に応じて期間を狭めて試験できる。

```powershell
uv run python -m uc_download.cli loop-request-links --period-start 2025-01-01 --period-end 2025-01-31
```


## 8. OTP 入力のタイミング

OTP は自動化していない。

`login-and-request` または `loop-request-links` を実行すると、ログイン押下後にブラウザが OTP 入力待機状態になる。
このとき利用者は以下を行う。

- メールで OTP を受け取る
- ブラウザ画面で OTP を入力する
- ログインを完了する

ログインが完了してパラメータ画面が表示されると、以降の処理は自動で進む。

この待機時間は `--wait-for-login-seconds` で変更できる。


## 9. 主なオプション

単発実行・全期間実行で共通の主なオプションは以下である。

- `--email`
  - ログインページへ入力するメールアドレス
- `--bbox-mode`
  - `auto` は bbox を自動入力する
  - `manual` は利用者が地図ハンドルを調整し、その値を今回の実行で採用する
- `--bbox-preset`
  - bbox プリセット名
- `--bbox-pad-deg`
  - bbox に足す余白量
- `--bbox`
  - bbox を直接指定するときに使う
- `--headless`
  - headless Chromium で実行する
- `--pause`
  - 正常終了時またはエラー時に、Enter を押すまでブラウザを閉じない
- `--wait-for-login-seconds`
  - OTP 完了後にパラメータ画面が出るまで待つ秒数
- `--wait-for-ok-seconds`
  - `変換開始` 後に OK や dialog を監視する秒数
- `--wait-for-page-ready-seconds`
  - 次期間へ進む前に元画面 ready を確認する秒数
- `--request-interval-seconds`
  - 各要求の間に入れる待機秒数
  - 既定値は `60` 秒
- `--retry-on-failure-count`
  - 失敗した期間を再試行する回数
  - 既定値は `1`（1 回再試行）
- `--retry-wait-seconds`
  - 再試行前の待機秒数
  - 既定値は `10` 秒
- `--stop-on-failed-window`
  - 失敗期間をスキップせず停止する
  - 既定では指定しないため、失敗期間はスキップして続行する

例:

```powershell
uv run python -m uc_download.cli login-and-request --start-day 2025-01-01 --days 3 --bbox-preset yamatogawa --bbox-pad-deg 0.02
```

手動 bbox モードの例:

```powershell
uv run python -m uc_download.cli loop-request-links --bbox-mode manual --period-start 2025-01-01 --period-end 2025-01-31
```

この場合は、OTP 完了後にパラメータ画面が表示された段階で、利用者が地図ハンドルを調整し、ターミナルで Enter を押す。
その時点で読み取れた bbox を、その実行全体で期待値として使う。

失敗期間の扱いは既定で以下になる。

1. 同じ期間を 1 回再試行する
2. それでも失敗したらその期間をスキップして次へ進む

失敗時に止めたい場合だけ `--stop-on-failed-window` を付ける。

ブラウザを閉じずに画面確認したい場合は `--pause` を付ける。

```powershell
uv run python -m uc_download.cli loop-request-links --bbox-mode manual --period-start 2025-01-01 --period-end 2025-01-31 --pause
```


## 10. 出力ファイル

既定では `outputs/uc_download` に以下が出力される。

- `period_plan.json`
- `run_config.json`
- `request_results.json`
- `run_summary.json`
- `screenshots/*.png`
- `mail_ingest/mail_entries.json`
- `mail_ingest/continuity_issues.json`
- `mail_ingest/mail_ingest_summary.json`
- `mail_ingest/raw/*.txt`
- `zip_results.json`
- `zip_fetch_summary.json`
- `download_manifest.json`
- `downloads/*.zip`


## 11. メール本文取り込み

貼り付け済みメール本文テキストを取り込みたい場合:

```powershell
uv run python -m uc_download.cli ingest-mail-bodies --input-file "docs\uc_download_automation\mail_data_temp\UC-Tools-降雨メール本文.txt"
```

標準入力から直接流したい場合:

```powershell
Get-Content -Raw "docs\uc_download_automation\mail_data_temp\UC-Tools-降雨メール本文.txt" | uv run python -m uc_download.cli ingest-mail-bodies --stdin
```

その場で本文を貼り付けたい場合:

```powershell
uv run python -m uc_download.cli ingest-mail-bodies --paste
```

起動後に本文を貼り付け、最後に単独行で `__END__` を入力すると取り込みが実行される。

画面で貼り付けと ZIP 取得をしたい場合:

```powershell
uv run python -m uc_download.cli launch-gui
```

GUI では `Ctrl+Shift+V` でクリップボード貼付、`Ctrl+Enter` で取り込み、`Ctrl+Shift+Enter` で取り込み後にそのまま ZIP 取得、`F5` で ZIP 取得を実行できる。`Ctrl+Enter` と `Ctrl+Shift+Enter` は成功時に貼り付け欄を自動でクリアする。

`自動監視` を ON にすると、クリップボード内容を定期監視し、`データ期間` と `ucrain.i-ric.info/download/` を含む本文を検知したときに自動で貼り付け、取り込みと `pending` の ZIP 取得まで実行する。

期待期間を与えて連続性チェックも同時に行いたい場合:

```powershell
uv run python -m uc_download.cli ingest-mail-bodies --input-file "docs\uc_download_automation\mail_data_temp\UC-Tools-降雨メール本文.txt" --expected-start 2010-01-02 --expected-end 2020-08-03
```

warning があっても保存を継続し、成功扱いで終了したい場合:

```powershell
uv run python -m uc_download.cli ingest-mail-bodies --input-file "docs\uc_download_automation\mail_data_temp\UC-Tools-降雨メール本文.txt" --expected-start 2010-01-02 --expected-end 2020-08-03 --allow-warnings
```

このコマンドは以下を行う。

1. 入力テキストをメール本文単位に分割する
2. 各本文からダウンロード URL とデータ期間を抽出する
3. raw テキストを保存する
4. `mail_entries.json` を更新する
5. `continuity_issues.json` を更新する
6. `mail_ingest_summary.json` を保存する

warning が検出された場合、既定では保存を行った上で非ゼロ終了する。warning を許容する場合だけ `--allow-warnings` を付ける。


## 12. ZIP 取得

保存済み URL から ZIP を取得したい場合:

```powershell
uv run python -m uc_download.cli fetch-zips --status pending
```

少数件だけ試験したい場合:

```powershell
uv run python -m uc_download.cli fetch-zips --status pending --limit 2
```

このコマンドは以下を行う。

1. `mail_entries.json` を読む
2. 対象 status の URL を列挙する
3. ZIP を `downloads` 配下へ保存する
4. `zip_results.json` を更新する
5. `download_manifest.json` を更新する
6. `zip_fetch_summary.json` を保存する

`failed` または `expired` が含まれる場合は、代表例が CLI ログにも表示される。


## 13. 現時点の未実装予定

現時点では、以下はまだ未実装である。

- `uc_rainfall` へ自動で渡すこと


## 14. 結果の見方

### 14.1 `request_results.json`

各期間ごとの結果が入る。

重要項目は以下である。

- `accepted`
  - `OK` または `dialog` を観測した明示成功
- `accepted_candidate`
  - `確認画面` タブ閉鎖のみを観測した暫定成功候補
- `failed`
  - 明示成功も暫定成功候補も取れていない失敗
- `parameter_bbox`
  - パラメータ画面から読み取れた bbox
- `confirm_bbox`
  - 確認画面から読み取れた bbox
- `server_error_tab_seen`
  - `500 Internal Server Error` 画面を検知したか
- `server_error_tab_closed`
  - 検知した `500` タブを自動クローズできたか
- `server_error_tab_url`
  - 検知した `500` 画面の URL
- `server_error_on_confirm_page`
  - `500` が確認タブ自身に表示されたか


### 14.2 `run_summary.json`

実行全体のサマリが入る。

重要項目は以下である。

- `processed_windows`
- `accepted_count`
- `accepted_candidate_count`
- `failed_count`
- `completed_all`
- `last_successful_window`
- `next_window`
- `retried_window_count`
- `skipped_window_count`
- `skipped_windows`
- `stopped_reason`


### 14.3 `mail_ingest_summary.json`

メール本文取り込みのサマリが入る。

重要項目は以下である。

- `input_block_count`
- `added_entry_count`
- `parse_failure_count`
- `duplicate_count`
- `warning_count`


### 14.4 `download_manifest.json`

要求送信結果、メール取込結果、ZIP 保存結果を横断した一覧が入る。

重要項目は以下である。

- `request_status`
- `mail_status`
- `zip_status`
- `zip_path`
- `http_status`
- `message`
- `response_preview`


## 15. トラブルシュート

### 15.1 パラメータ画面へ進まない

確認項目:

- OTP を正しく入力したか
- `--wait-for-login-seconds` が短すぎないか
- ブラウザを途中で閉じていないか


### 15.2 `accepted_candidate` が多い

意味:

- 確認タブ閉鎖は見えたが、`OK` や `dialog` は取れていない

対応:

- スクリーンショットを確認する
- メール到着有無と突き合わせる
- `--wait-for-ok-seconds` を増やして再試行する


### 15.3 bbox 不一致で止まる

意味:

- パラメータ画面または確認画面に表示された緯度経度が、期待した大和川流域 bbox と一致していない

対応:

- `request_results.json` の `parameter_bbox` と `confirm_bbox` を確認する
- スクリーンショットを確認する
- 必要なら GUI 操作が必要かを再評価する


### 15.4 途中で停止した

確認ファイル:

- `run_summary.json`
- `request_results.json`

見るべき項目:

- `stopped_reason`
- `last_successful_window`
- `next_window`

再開方法:

- `next_window.start_date` を `--period-start` に指定して再開する
- 例:

```powershell
uv run python -m uc_download.cli loop-request-links --period-start 2025-01-13 --period-end 2025-12-31
```


### 15.5 `500 Internal Server Error` が表示された

意味:

- `変換開始` 押下後にサーバー側エラー画面が表示された

現在の挙動:

- `500` 画面を検知したら自動で閉じる
- 検知情報は `request_results.json` に保存する
- その期間が失敗した場合は実行を止め、`next_window` を出力する

対応:

- `request_results.json` の `server_error_tab_*` を確認する
- `run_summary.json` の `next_window` から再開する


### 15.6 メール本文取り込みで duplicate が出る

意味:

- 同じ期間または同じ `source_id` のメール本文が既に登録されている

対応:

- `mail_ingest_summary.json` の `duplicates` を確認する
- 同じ本文を再投入していないか確認する
- 意図した再取込であれば既存 entry を整理してから再実行する


### 15.7 ZIP 取得が失敗する

確認項目:

- `zip_fetch_summary.json`
- `zip_results.json`
- `download_manifest.json`

見るべき項目:

- `status`
- `http_status`
- `message`


## 16. 現時点の対象外

現時点では以下はまだ実装対象外である。

- メール受信箱の自動操作
- メール本文のコピーや貼り付けそのものの自動化
- `uc_rainfall` へ自動で渡すこと

このうち、`uc_rainfall` 連携は次段階で扱う予定である。
