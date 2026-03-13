# UC ダウンロード自動化 利用手順

## 1. 目的

本書は、`src/uc_download` に実装した UC ダウンロード自動化機能の使い方をまとめる。

初期実装の対象は、ログインページから開始し、人手で OTP を入力した後、解析雨量のダウンロードリンク送信要求を自動で実行するところまでである。

ZIP の実ダウンロードや `uc_rainfall` への取り込みは、本書の対象外である。


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

初期実装の既定値は以下である。

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


## 11. 結果の見方

### 11.1 `request_results.json`

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


### 11.2 `run_summary.json`

実行全体のサマリが入る。

重要項目は以下である。

- `processed_windows`
- `accepted_count`
- `accepted_candidate_count`
- `failed_count`
- `completed_all`
- `last_successful_window`
- `next_window`
- `stopped_reason`


## 12. トラブルシュート

### 12.1 パラメータ画面へ進まない

確認項目:

- OTP を正しく入力したか
- `--wait-for-login-seconds` が短すぎないか
- ブラウザを途中で閉じていないか


### 12.2 `accepted_candidate` が多い

意味:

- 確認タブ閉鎖は見えたが、`OK` や `dialog` は取れていない

対応:

- スクリーンショットを確認する
- メール到着有無と突き合わせる
- `--wait-for-ok-seconds` を増やして再試行する


### 12.3 bbox 不一致で止まる

意味:

- パラメータ画面または確認画面に表示された緯度経度が、期待した大和川流域 bbox と一致していない

対応:

- `request_results.json` の `parameter_bbox` と `confirm_bbox` を確認する
- スクリーンショットを確認する
- 必要なら GUI 操作が必要かを再評価する


### 12.4 途中で停止した

確認ファイル:

- `run_summary.json`
- `request_results.json`

見るべき項目:

- `stopped_reason`
- `last_successful_window`
- `next_window`


## 13. 今後の対象外

本書時点では以下はまだ実装対象外である。

- メールリンクを自動で開くこと
- ZIP を自動で保存すること
- `uc_rainfall` へ自動で渡すこと

これらは次段階の実装で扱う。
