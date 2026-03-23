# GUI利用ガイド
docs/uc_rainfall_zipflow/usage_gui.md

# rust_pyo3 本番運用（wheel）
`rust_pyo3` エンジンを本番利用する場合は、`weighted_core_pyo3` を wheel 化してインストールします。

## 前提
- Rust toolchain（`cargo`）が使えること
- `uv sync` 済みであること（`maturin` は dev 依存に追加済み）

## 手順（Windows / PowerShell）
1. build + install + verify（推奨）
   - `pwsh -File scripts/pyo3_wheel.ps1 -Action all`
2. build のみ
   - `pwsh -File scripts/pyo3_wheel.ps1 -Action build`
3. 既存 wheel の install のみ
   - `pwsh -File scripts/pyo3_wheel.ps1 -Action install`
4. import/計算の verify のみ
   - `pwsh -File scripts/pyo3_wheel.ps1 -Action verify`

wheel は `dist/wheels/` に出力されます。
