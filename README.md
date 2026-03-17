uv run python scripts\uc_download_playwright_probe.py login-and-request-link --email yuuta.ochiai@tk.pacific.co.jp --start-day 2025-01-01 --days 3 --bbox-preset yamatogawa --bbox-pad-deg 0.02 --pause


# CSVなし（疑似データ）
uv run python -m uc_rainfall_zipflow.cli style-gui --value-kind mean --sample-mode synthetic --profile-path config/uc_rainfall_zipflow/styles/default.json