# UC ダウンロード自動化 詳細設計

## 1. 目的

本書は、`requirements.md` および `experiment_results.md` を受けて、既存実装の維持点と後段拡張の詳細設計を定義する。

対象は、以下の 3 段階の機能とする。

- フェーズ 1: 既存実装として、ログインページから開始し、人手による OTP 入力後に同一ブラウザセッションで解析雨量のダウンロードリンク送信要求を繰り返し発行する
- フェーズ 2: 新仕様として、人手でコピーしたメール本文を貼り付け入力し、ダウンロード URL とデータ期間を抽出して保存する
- フェーズ 3: 新仕様として、保存済み URL を用いて ZIP を取得し、対象期間との対応を manifest として保存する


## 2. 実装対象範囲

既存実装として成立済みのもの:

- `tools.i-ric.info/login/` を開く
- メールアドレス入力と `ログイン` 押下
- OTP 完了後のパラメータ画面遷移待機
- 開始日、日数、bbox の設定
- `確認画面` の別タブ捕捉
- `変換開始` の押下
- 要求受理シグナルの検知
- `2010-01-02` から `2025-12-31` までの 3 日単位ループ
- 実行ログ、結果 JSON、スクリーンショット保存

今回の拡張実装で追加するもの:

- メール本文の貼り付け入力受付
- メール本文からの URL とデータ期間の抽出
- 取り込み済みメール群に対する連続性、重複、欠落チェック
- 保存済み URL に対する ZIP ダウンロード
- 期間と ZIP の対応を manifest として保存
- 機械判定による取り込み結果と ZIP 取得結果の保存
- メール本文貼り付けと ZIP 取得を補助する簡易 GUI

今回の拡張実装でも実施しないもの:

- OTP の自動取得
- メール受信箱の自動操作
- メール本文のコピーや貼り付けそのものの自動化
- `uc_rainfall` への自動取り込み


## 3. ディレクトリ構成案

実装ファイルは `src` 配下で以下のように分割する。前段は概ね実装済みであり、後段ファイルを追加する想定とする。

```text
src/
  uc_download/
    __init__.py
    cli.py
    gui.py
    models.py
    config.py
    selectors.py
    period_planner.py
    result_store.py
    mail_parser.py
    continuity_checker.py
    download_store.py
    zip_downloader.py
    gui.py
    browser.py
    workflows/
      __init__.py
      login_workflow.py
      request_workflow.py
      loop_workflow.py
      mail_ingest_workflow.py
      zip_fetch_workflow.py
    pages/
      __init__.py
      login_page.py
      parameter_page.py
      confirm_page.py
```


## 4. コンポーネント詳細設計

### 4.1 `config.py`

用途:

- 既存の既定値と、後段拡張で追加する実行設定をまとめる

保持内容:

- ログイン URL
- パラメータ画面 URL
- 既定メールアドレス
- 既定 output ディレクトリ
- 既定 profile ディレクトリ
- 大和川流域 bbox プリセット
- bbox 余白既定値
- 期間既定値
- メール本文取り込み用の既定 output ディレクトリ
- ZIP 保存先ディレクトリ
- ZIP ダウンロード時のタイムアウトや再試行設定

既存実装の既定値:

- login URL: `https://tools.i-ric.info/login/`
- parameter URL: `https://tools.i-ric.info/confirm/`
- email: `yuuta.ochiai@tk.pacific.co.jp`
- period start: `2010-01-02`
- period end: `2025-12-31`
- chunk days: `3`
- bbox preset: `yamatogawa`
- bbox pad: `0.02`

拡張時に追加する既定値:

- mail ingest dir: `outputs/uc_download/mail_ingest`
- zip dir: `outputs/uc_download/downloads`


### 4.2 `models.py`

用途:

- 既存ワークフローと、後段拡張ワークフロー間で受け渡すデータ構造を定義する

既存実装済み dataclass:

```python
@dataclass(frozen=True)
class BBox:
    south: float
    north: float
    west: float
    east: float


@dataclass(frozen=True)
class RequestWindow:
    start_date: date
    end_date: date
    days: int


@dataclass(frozen=True)
class RunConfig:
    login_url: str
    parameter_url: str
    email: str
    bbox: BBox
    output_dir: Path
    profile_dir: Path
    wait_for_login_seconds: float
    wait_for_ok_seconds: float


@dataclass(frozen=True)
class RequestResult:
    window: RequestWindow
    accepted: bool
    accepted_candidate: bool
    final_url: str | None
    parameter_page_detected: bool
    confirm_page_detected: bool
    dialog_seen: bool
    ok_clicked: bool
    confirm_tab_closed: bool
    screenshot_paths: tuple[Path, ...]
    message: str | None
```

拡張時に追加する dataclass:

```python


@dataclass(frozen=True)
class MailEntry:
    source_id: str
    download_url: str
    period_start: date
    period_end: date
    raw_body_path: Path
    ingested_at: datetime


@dataclass(frozen=True)
class ContinuityIssue:
    issue_type: str
    severity: str
    previous_period_end: date | None
    current_period_start: date | None
    current_period_end: date | None
    message: str


@dataclass(frozen=True)
class ZipDownloadResult:
    source_id: str
    download_url: str
    period_start: date
    period_end: date
    zip_path: Path | None
    status: str
    http_status: int | None
    downloaded_at: datetime | None
    message: str | None
```

備考:

- `accepted` は `OK` または `dialog` が観測されたとき `True`
- `accepted_candidate` は `OK` / `dialog` は見えていないが、確認タブ閉鎖が起きたとき `True`
- 後段で CSV/JSON 出力しやすいよう、単純なスカラー項目を中心にする
- `MailEntry.source_id` は URL と期間から導ける一意キーとする
- `ZipDownloadResult.status` は `downloaded`, `failed`, `already_exists` を現行実装の基本状態とする
- 将来、期限切れ URL を識別できる場合は `expired` を追加可能とする


### 4.3 `gui.py`

用途:

- メール本文貼り付け、クリップボード貼付、ZIP 取得を行う簡易 GUI を提供する

責務:

- メール本文貼り付け欄を表示する
- `ingest_mail_bodies()` を GUI から実行する
- `fetch_zips()` を GUI から実行する
- クリップボード監視 ON/OFF を切り替える
- `データ期間` と `ucrain.i-ric.info/download/` を含む本文を検知したら自動取り込みを実行する
- `Ctrl+Enter`, `Ctrl+Shift+Enter`, `F5` などのショートカットを提供する


### 4.4 `selectors.py`

用途:

- selector を一元管理する

初期実装で必要な selector:

- ログインページ
  - `input[type="email"][name="email"]`
  - `input[type="submit"][value="ログイン"]`
- パラメータ画面
  - `#start_day`
  - `select[name="days"]`
  - `input[name="south"]`
  - `input[name="nouth"]`
  - `input[name="west"]`
  - `input[name="east"]`
  - `input[type="submit"][value="確認画面"]`
- 確認画面
  - `input[type="submit"][value="変換開始"]`
  - `input[type="submit"][value="キャンセル"]`
- `OK` 検知候補
  - role button `OK`
  - role link `OK`
  - `input[value="OK"]`
  - text `OK`

方針:

- selector は文字列定数として 1 か所に集約する
- 画面改修時はこのファイルの差し替えを優先する


### 4.4 `period_planner.py`

用途:

- 全期間を 3 日単位へ分割する

責務:

- `start_date`, `end_date`, `chunk_days` を受け取る
- `RequestWindow` の配列を返す
- 末尾だけ 1 日または 2 日になるケースを扱う

入出力例:

- 入力: `2010-01-02`, `2025-12-31`, `3`
- 出力先頭: `2010-01-02` から `2010-01-04`
- 出力末尾: `2025-12-30` から `2025-12-31`


### 4.5 `result_store.py`

用途:

- 実行結果の保存を担当する

保存対象:

- 実行設定
- 各期間の成否
- スクリーンショットパス
- 失敗理由
- 実行開始時刻・終了時刻

初期実装の保存形式:

- JSON

想定ファイル:

- `outputs/uc_download/run_config.json`
- `outputs/uc_download/request_results.json`
- `outputs/uc_download/run_summary.json`

将来拡張:

- CSV の追記出力
- 途中保存による再開支援
- メール取込結果と ZIP 取得結果の統合出力


### 4.6 `mail_parser.py`

用途:

- 貼り付けられたメール本文から構造化データを抽出する

責務:

- 1 件のメール本文から URL とデータ期間を抽出する
- 連結された複数件の本文からメール単位へ分割する
- 抽出失敗時に理由を返す

抽出対象:

- `https://ucrain.i-ric.info/download/...`
- `データ期間：YYYY-MM-DD～YYYY-MM-DD`

実装方針:

- 正規表現ベースで抽出する
- Outlook 由来の余分な空行や前後テキストがあっても抽出できるようにする
- 解析不能な本文は raw text を保存したうえで失敗として記録する


### 4.7 `continuity_checker.py`

用途:

- メール本文から抽出した期間一覧の整合性を検査する

責務:

- 期間を開始日順に並べる
- 連続性の確認
- 重複区間の検出
- 欠落区間の検出
- 期待期間に対する網羅率の確認

判定対象:

- `gap`
- `overlap`
- `duplicate`
- `out_of_range`

実装方針:

- 判定結果は `ContinuityIssue` の配列で返す
- 警告があっても保存を禁止するのではなく、利用者判断で続行可能とする
- 続行時は issue 一覧をそのまま保存する


### 4.8 `download_store.py`

用途:

- メール取込結果と ZIP 取得結果を永続化する

保存対象:

- raw のメール本文
- 構造化済みメールエントリ
- 整合性チェック結果
- ZIP ダウンロード結果
- 統合 manifest

想定ファイル:

- `outputs/uc_download/mail_ingest/raw/*.txt`
- `outputs/uc_download/mail_ingest/mail_entries.json`
- `outputs/uc_download/mail_ingest/continuity_issues.json`
- `outputs/uc_download/download_manifest.json`


### 4.9 `zip_downloader.py`

用途:

- 保存済み URL から ZIP を取得する

責務:

- HTTP GET を行う
- Content-Type や拡張子を確認する
- ZIP を保存する
- 既存ファイルと重複する場合は再取得を避ける
- ダウンロード結果を `ZipDownloadResult` で返す

実装方針:

- requests または httpx を利用する
- ストリーミング保存を基本とする
- 期間ベースの規則的なファイル名を採用する
- 保存後にファイルサイズ 0 を弾く


### 4.10 `browser.py`

用途:

- Playwright とブラウザ起動処理をまとめる

責務:

- Chromium の起動
- viewport 設定
- headed 実行
- context の生成
- page の取り出し
- timeout 設定

初期方針:

- `launch_persistent_context` は使わず、同一プロセス・同一 context を基本とする
- 理由:
  - 実験で、ブラウザを閉じるとセッション再利用が成立しなかった
  - 本件では 1 回の長時間実行を主方式にするため、永続再開より連続稼働が重要

補足:

- 後で失敗復旧のために persistent context を補助的に残す余地はある
- ただし初期実装の主設計は「閉じないこと」である


## 5. ページオブジェクト詳細設計

### 5.1 `pages/login_page.py`

用途:

- ログインページの操作を担当する

責務:

- ログインページを開く
- メールアドレスを入力する
- `ログイン` を押す
- ログインページの存在確認を行う

主要メソッド案:

```python
class LoginPage:
    def goto(self) -> None: ...
    def fill_email(self, email: str) -> None: ...
    def submit(self) -> None: ...
    def is_visible(self) -> bool: ...
```


### 5.2 `pages/parameter_page.py`

用途:

- パラメータ画面の操作を担当する

責務:

- パラメータ画面の存在確認
- 開始日設定
- 日数設定
- bbox 設定
- `確認画面` の押下
- popup 取得

主要メソッド案:

```python
class ParameterPage:
    def wait_until_ready(self, timeout_seconds: float) -> None: ...
    def set_start_day(self, value: str) -> None: ...
    def set_days(self, value: int) -> None: ...
    def set_bbox(self, bbox: BBox) -> None: ...
    def open_confirm_popup(self) -> Page: ...
```

実装方針:

- bbox はハンドル操作ではなく、readonly input の値更新を第一候補とする
- `input` と `change` イベントを発火する


### 5.3 `pages/confirm_page.py`

用途:

- 確認画面の操作と要求受理の検知を担当する

責務:

- 確認画面の存在確認
- `変換開始` の押下
- `OK`、`dialog`、タブ閉鎖の検知

主要メソッド案:

```python
class ConfirmPage:
    def wait_until_ready(self) -> None: ...
    def start_convert(self) -> None: ...
    def wait_for_acceptance(self, timeout_seconds: float) -> AcceptanceResult: ...
```

Acceptance 判定:

- `dialog_seen`
- `ok_clicked`
- `page_closed`

判定ルール:

- `dialog_seen` または `ok_clicked` が成立したとき `accepted=True`
- `page_closed` のみ成立したとき `accepted_candidate=True`
- いずれも成立しないとき失敗


## 6. ワークフロー詳細設計

### 6.1 `workflows/login_workflow.py`

用途:

- ログイン開始から OTP 完了待機までを担当する

処理順:

1. ログインページを開く
2. メールアドレスを入力する
3. `ログイン` を押す
4. OTP 入力は人手に委ねる
5. パラメータ画面が出るまで待機する

待機方式:

- `#start_day` と `select[name="days"]` が見えるまで polling
- 既定 300 秒

異常系:

- タイムアウト
- ブラウザが閉じられた
- パラメータ画面へ遷移しない


### 6.2 `workflows/request_workflow.py`

用途:

- 1 期間ぶんのリンク送信要求を担当する

処理順:

1. 開始日設定
2. 日数設定
3. bbox 設定
4. パラメータ画面に反映された bbox を読み取り、期待値と照合する
5. パラメータ画面のスクリーンショット保存
6. `確認画面` を押す
7. popup の確認画面を取得
8. 確認画面に表示された bbox を読み取り、期待値と照合する
9. 確認画面のスクリーンショット保存
10. `変換開始` を押す
11. 受理シグナルを待つ
12. `RequestResult` を返す

正常完了条件:

- `OK` が押せた場合は `accepted`
- `dialog` が出た場合は `accepted`
- `確認画面` タブが閉じただけの場合は `accepted_candidate`

備考:

- 実験結果から、確認タブ閉鎖は要求受理の可能性が高い
- ただし、最終集計では `accepted` と混在させない


### 6.3 `workflows/loop_workflow.py`

用途:

- 全期間ループを担当する

処理順:

1. `period_planner.py` で `RequestWindow` 一覧を作る
2. 先頭から順に `request_workflow` を呼ぶ
3. 各結果を逐次保存する
4. 各要求後に元のパラメータ画面が再利用可能か確認する
5. 設定された待機時間だけ安定待機する
6. 失敗時は停止し、最後の成功期間と失敗期間を記録する

停止条件:

- 明示的な要求送信失敗
- セッション切れ
- パラメータ画面が消失
- 元画面の ready 再確認に失敗
- 想定外例外

初期実装方針:

- 途中失敗時に自動再開はしない
- まずは「どこまで通ったか」が分かることを優先する
- 要求間隔は設定値で制御できるようにする
- `accepted_candidate` のみ連続した場合も件数を分けて集計する


### 6.4 `workflows/mail_ingest_workflow.py`

用途:

- 貼り付けられたメール本文を取り込み、構造化保存と整合性チェックを行う

処理順:

1. 入力テキストを受け取る
2. 複数メールが連結されている場合は 1 件ずつへ分割する
3. 各メール本文から URL とデータ期間を抽出する
4. raw text をファイルとして保存する
5. `MailEntry` 一覧を保存する
6. 既存エントリを含めて連続性チェックを実行する
7. issue 一覧を保存する
8. 取り込み結果サマリを返す

異常系:

- 本文を 1 件も抽出できない
- URL が見つからない
- 期間が見つからない
- 既存エントリとの重複がある

備考:

- 取り込み失敗 1 件で全体停止するのではなく、成功件と失敗件を分けて保存する
- 取り込み結果は `ingested`, `duplicate`, `parse_failed` などの機械判定として保存する


### 6.5 `workflows/zip_fetch_workflow.py`

用途:

- 保存済みメールエントリから ZIP を取得し、manifest を更新する

処理順:

1. 未取得または再取得対象の `MailEntry` を列挙する
2. 1 件ずつ URL へアクセスする
3. ZIP を保存する
4. 保存結果を `ZipDownloadResult` として記録する
5. 統合 manifest を更新する

停止条件:

- 認証切れなどで URL が無効
- ZIP ではない応答が返る
- 保存先へ書き込めない

実装方針:

- 1 件失敗しても全体停止しない
- 全件処理後に成功件数、失敗件数、既取得再利用件数を集計する


## 7. CLI 詳細設計

### 7.1 エントリポイント

モジュール入口は `python -m uc_download.cli` とする。


### 7.2 コマンド構成案

#### `plan-periods`

用途:

- 全期間の要求窓を生成する

例:

```bash
uv run python -m uc_download.cli plan-periods
```


#### `login-and-request`

用途:

- ログイン開始から 1 期間の要求送信までを同一ブラウザで実行する

例:

```bash
uv run python -m uc_download.cli login-and-request \
  --email yuuta.ochiai@tk.pacific.co.jp \
  --start-day 2025-01-01 \
  --days 3 \
  --bbox-preset yamatogawa
```


#### `loop-request-links`

用途:

- 全期間に対して連続でリンク送信要求を実行する

例:

```bash
uv run python -m uc_download.cli loop-request-links \
  --email yuuta.ochiai@tk.pacific.co.jp \
  --bbox-preset yamatogawa \
  --period-start 2010-01-02 \
  --period-end 2025-12-31 \
  --chunk-days 3
```


#### `ingest-mail-bodies`

用途:

- 貼り付けたメール本文を解析して保存する

方針:

- `--input-file` 指定時はファイルから読む
- `--stdin` 指定時、または入力ファイル未指定かつ標準入力がパイプされている場合は標準入力から読む
- gap / overlap / out_of_range などの warning が出た場合は、既定では非ゼロ終了にする
- warning を許容して保存を継続したい場合だけ `--allow-warnings` を指定する

例:

```bash
uv run python -m uc_download.cli ingest-mail-bodies \
  --input-file docs/uc_download_automation/mail_data_temp/UC-Tools-降雨メール本文.txt
```


#### `fetch-zips`

用途:

- 保存済み URL から ZIP を取得する

方針:

- summary の件数だけでなく、`failed` または `expired` の代表例を CLI 末尾に表示する
- 代表例には少なくとも `source_id`, 期間, status, message を含める

例:

```bash
uv run python -m uc_download.cli fetch-zips \
  --status pending
```


#### `launch-gui`

用途:

- メール本文貼り付けと ZIP 取得のための簡易 GUI を開く

例:

```bash
uv run python -m uc_download.cli launch-gui
```


## 8. 実行結果ファイル設計

### 8.1 出力ディレクトリ

第一候補:

- `outputs/uc_download`


### 8.2 生成ファイル

想定:

- `outputs/uc_download/period_plan.json`
- `outputs/uc_download/run_config.json`
- `outputs/uc_download/request_results.json`
- `outputs/uc_download/run_summary.json`
- `outputs/uc_download/screenshots/*.png`
- `outputs/uc_download/mail_ingest/raw/*.txt`
- `outputs/uc_download/mail_ingest/mail_entries.json`
- `outputs/uc_download/mail_ingest/continuity_issues.json`
- `outputs/uc_download/download_manifest.json`
- `outputs/uc_download/downloads/*.zip`


### 8.3 `request_results.json` の項目案

```json
[
  {
    "start_date": "2025-01-01",
    "end_date": "2025-01-03",
    "days": 3,
    "accepted": false,
    "accepted_candidate": true,
    "dialog_seen": false,
    "ok_clicked": false,
    "confirm_tab_closed": true,
    "message": null
  }
]
```


### 8.4 `mail_entries.json` の項目案

```json
[
  {
    "source_id": "20100102_20100104_158261951",
    "download_url": "https://ucrain.i-ric.info/download/158261951",
    "period_start": "2010-01-02",
    "period_end": "2010-01-04",
    "raw_body_path": "outputs/uc_download/mail_ingest/raw/20100102_20100104_158261951.txt",
    "ingested_at": "2026-03-13T10:30:00"
  }
]
```


### 8.5 `download_manifest.json` の項目案

```json
[
  {
    "source_id": "20100102_20100104_158261951",
    "window": {
      "start_date": "2010-01-02",
      "end_date": "2010-01-04"
    },
    "request_status": "accepted",
    "mail_status": "ingested",
    "zip_status": "downloaded",
    "download_url": "https://ucrain.i-ric.info/download/158261951",
    "zip_path": "outputs/uc_download/downloads/20100102_20100104.zip",
    "message": null,
    "response_preview": null
  }
]
```


## 9. ログ設計

最低限のログ対象:

- ログインページを開いた
- メールアドレスを入力した
- `ログイン` を押した
- OTP 待機を開始した
- パラメータ画面へ到達した
- 期間設定を行った
- `確認画面` を開いた
- `変換開始` を押した
- `accepted` を検知した
- `accepted_candidate` を検知した
- 元画面の再利用可否を確認した
- 次期間までの待機を開始した
- 次の期間へ進む
- 失敗して停止した
- メール本文を取り込んだ
- 期間の gap / overlap / duplicate を検知した
- ZIP ダウンロードを開始した
- ZIP ダウンロードが成功した
- ZIP ダウンロードが失敗した

ログ方針:

- 日本語ログを基本とする
- 期間識別子を必ず含める
- スクリーンショットパスを記録する


## 10. エラー処理設計

最低限の異常系:

- ログインページへ到達できない
- OTP 完了後にパラメータ画面が出ない
- パラメータ画面 selector が消える
- `確認画面` popup が開かない
- `変換開始` 押下後に `accepted` も `accepted_candidate` も取れない
- 次期間へ進む前の元画面 ready 再確認に失敗する
- メール本文から URL を抽出できない
- メール本文から期間を抽出できない
- 期間整合性チェックで不整合が検出される
- ZIP がダウンロードできない
- ZIP 保存後の manifest 更新に失敗する

対応方針:

- メール取り込みの warning は、保存結果と issue 保存を行った上で非ゼロ終了として返せるようにする
- ZIP 取得失敗時は、summary に加えて代表的な失敗例を CLI に表示する

- 例外を握りつぶさない
- 失敗時点の期間を `RequestResult` として保存する
- 停止前にスクリーンショットを残す


## 11. `uc_rainfall` との接続点

本実装では `uc_rainfall` 連携自体はまだ行わないが、後段連携を見据えて以下を保つ。

- 期間窓を機械可読に保存する
- 要求送信結果を機械可読に保存する
- 後でメールリンクから取得した ZIP を期間と対応付けられる構造にする

将来は以下の流れへ接続する。

1. `uc_download` が期間ごとにリンク送信要求を発行する
2. 人手で取得したメール本文を `uc_download` へ取り込む
3. `uc_download` が URL から ZIP を取得する
4. ZIP を `uc_rainfall` へ渡す


## 12. 将来拡張の接続点

詳細設計上、以下は拡張可能な構造にしておく。

- 複数期間の連続送信後にメールリンク取得を接続する
- メール貼り付け UI を簡易 GUI へ差し替える
- 途中失敗からの再開
- 複数 bbox プリセット
- 実行状態の GUI 表示
- `uc_rainfall` への一括引き渡し
