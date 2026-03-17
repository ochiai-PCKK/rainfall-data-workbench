# UC Rainfall ZIP Flow グラフスタイル調整 タスク分解

## 1. ステータス運用

- `pending`: 未着手
- `partial`: 一部実装済み
- `done`: 実装・導線・確認完了

## 2. フェーズ1: モデル化

### ST1. スタイルパラメータモデル定義

Status: `done`  
Check: `code`

- `GraphStyleProfile`（dataclass）を定義
- デフォルト値を現行 `graph_renderer_reference.py` に合わせて定義

### ST2. JSON 入出力ユーティリティ実装

Status: `done`  
Check: `code`

- `save_profile(path, profile)` を実装
- `load_profile(path)` を実装
- バリデーションとフォールバックを実装

## 3. フェーズ2: レンダラ統合

### ST3. `graph_renderer_reference` の引数化

Status: `done`  
Check: `code`

- 現在ハードコードしている体裁値を `GraphStyleProfile` 参照へ切替
- 未指定時はデフォルトプロファイル適用

### ST4. CLI プロファイル適用

Status: `done`  
Check: `code`

- `--style-profile` 追加
- `plots_ref` 出力時にプロファイルを注入
- 既存挙動（未指定）を維持

## 4. フェーズ3: GUI

### ST5. 体裁調整 GUI 雛形

Status: `done`  
Check: `code`

- Tkinter で調整画面を作成
- 左: パラメータ入力、右: プレビュー

### ST6. 即時プレビュー更新

Status: `done`  
Check: `code`

- 値変更イベントで再描画
- Figure/Axes 再利用で高速化

### ST7. プロファイル保存/読込 UI

Status: `done`  
Check: `code`

- 「保存」「読込」「デフォルトへ戻す」を実装
- エラー時メッセージ表示を実装

## 5. フェーズ4: 接続と検証

### ST8. CSV 入力導線

Status: `done`  
Check: `code`

- `*_timeseries.csv` の読み込み
- `sum/mean` 切替プレビュー

### ST9. 回帰確認

Status: `partial`  
Check: `manual`

- 既存 `plots_ref` 出力との差分確認（デフォルトプロファイル）
- `--style-profile` 指定時の出力確認

### ST10. ドキュメント反映

Status: `done`  
Check: `docs`

- `usage.md` に GUI 起動方法と `--style-profile` 追記
- 実運用例（保存→CLI適用）を追記

## 6. 実装順

1. ST1
2. ST2
3. ST3
4. ST4
5. ST5
6. ST6
7. ST7
8. ST8
9. ST9
10. ST10
