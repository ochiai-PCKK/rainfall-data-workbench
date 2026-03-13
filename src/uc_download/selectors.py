from __future__ import annotations

"""ページ操作に使う selector 定義。"""

LOGIN_EMAIL = 'input[type="email"][name="email"]'
LOGIN_SUBMIT = 'input[type="submit"][value="ログイン"]'

PARAMETER_START_DAY = "#start_day"
PARAMETER_DAYS = 'select[name="days"]'
PARAMETER_SOUTH = 'input[name="south"]'
PARAMETER_NORTH = 'input[name="nouth"]'
PARAMETER_WEST = 'input[name="west"]'
PARAMETER_EAST = 'input[name="east"]'
PARAMETER_CONFIRM_SUBMIT = 'input[type="submit"][value="確認画面"]'

CONFIRM_START_CONVERT = 'input[type="submit"][value="変換開始"]'
CONFIRM_CANCEL = 'input[type="submit"][value="キャンセル"]'
CONFIRM_LAT_S = 'input[name="lat_s"]'
CONFIRM_LAT_N = 'input[name="lat_n"]'
CONFIRM_LNG_W = 'input[name="lng_w"]'
CONFIRM_LNG_E = 'input[name="lng_e"]'

OK_INPUT = 'input[value="OK"]'
OK_TEXT = "text=OK"
