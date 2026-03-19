from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tkinter import ttk
from typing import Callable

from ..models import ZipWindow
from ..zip_selector import list_zip_windows

_WINDOW_MODE_LABELS = {
    "5d": "5日",
    "3d_left": "3日前寄せ",
    "3d_center": "3日中央",
    "3d_right": "3日後寄せ",
}
_PERIOD_INPUT_MODE_LABELS = {
    "manual_range": "期間を直接指定",
    "auto_dates": "対象日から自動設定（複数可）",
}


@dataclass
class RainModePanel:
    parent: tk.Misc
    frame: ttk.Frame
    input_zip_row: ttk.Frame
    period_input_mode_var: tk.StringVar
    window_mode_var: tk.StringVar
    date_listbox: tk.Listbox
    candidate_count_var: tk.StringVar
    selected_count_var: tk.StringVar
    refresh_button: ttk.Button
    import_excel_button: ttk.Button
    graph_period_radios: list[ttk.Radiobutton]
    zip_windows_cache: dict[str, list[ZipWindow]]
    period_start_entry: ttk.Entry
    period_end_entry: ttk.Entry
    period_row: ttk.Frame
    graph_period_row: ttk.Frame
    period_input_mode_row: ttk.Frame

    @classmethod
    def create(
        cls,
        parent: tk.Misc,
        *,
        build_path_row: Callable[..., ttk.Frame],
        input_zip_var: tk.StringVar,
        start_date_var: tk.StringVar,
        end_date_var: tk.StringVar,
        on_change: Callable[[], None] | None = None,
        on_import_excel: Callable[[], None] | None = None,
    ) -> "RainModePanel":
        frame = ttk.Frame(parent)
        period_input_mode_var = tk.StringVar(value="manual_range")
        window_mode_var = tk.StringVar(value="5d")
        candidate_count_var = tk.StringVar(value="候補日: 0件")
        selected_count_var = tk.StringVar(value="選択中: 0件")

        input_zip_row = build_path_row(frame, "入力ZIPディレクトリ", input_zip_var, ask_dir=True)

        row_input_mode = ttk.Frame(frame)
        row_input_mode.pack(fill=tk.X, pady=(2, 2))
        row_input_mode.columnconfigure(1, weight=1)
        ttk.Label(row_input_mode, text="期間指定方式").grid(row=0, column=0, sticky="w", padx=(0, 6))
        input_mode_wrap = ttk.Frame(row_input_mode)
        input_mode_wrap.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            input_mode_wrap,
            text="期間を直接指定",
            value="manual_range",
            variable=period_input_mode_var,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(
            input_mode_wrap,
            text="対象日から自動設定（複数可）",
            value="auto_dates",
            variable=period_input_mode_var,
        ).pack(side=tk.LEFT)

        period_row = ttk.Frame(frame)
        period_row.pack(fill=tk.X, pady=(2, 2))
        period_row.columnconfigure(1, weight=1)
        ttk.Label(period_row, text="期間指定").grid(row=0, column=0, sticky="w", padx=(0, 6))
        period_input_wrap = ttk.Frame(period_row)
        period_input_wrap.grid(row=0, column=1, sticky="w")
        period_start_entry = ttk.Entry(period_input_wrap, textvariable=start_date_var, width=15)
        period_start_entry.pack(side=tk.LEFT)
        ttk.Label(period_input_wrap, text="〜", padding=(6, 0)).pack(side=tk.LEFT)
        period_end_entry = ttk.Entry(period_input_wrap, textvariable=end_date_var, width=15)
        period_end_entry.pack(side=tk.LEFT)
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(toolbar, text="対象日候補（複数選択可）", width=22).pack(side=tk.LEFT)
        import_excel_button = ttk.Button(toolbar, text="Excel候補日取込", command=lambda: None)
        import_excel_button.pack(side=tk.RIGHT, padx=(4, 0))
        refresh_button = ttk.Button(toolbar, text="候補更新", command=lambda: None, width=8)
        refresh_button.pack(side=tk.RIGHT)

        list_wrap = ttk.Frame(frame)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 2))
        date_listbox = tk.Listbox(list_wrap, selectmode=tk.EXTENDED, height=10, exportselection=False)
        date_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL, command=date_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        date_listbox.configure(yscrollcommand=scroll.set)
        count_row = ttk.Frame(frame)
        count_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(count_row, textvariable=candidate_count_var).pack(side=tk.LEFT)
        ttk.Label(count_row, textvariable=selected_count_var).pack(side=tk.RIGHT)

        row_mode = ttk.Frame(frame)
        row_mode.pack(fill=tk.X, pady=(2, 2))
        row_mode.columnconfigure(1, weight=1)
        ttk.Label(row_mode, text="グラフ期間").grid(row=0, column=0, sticky="w", padx=(0, 6))
        mode_wrap = ttk.Frame(row_mode)
        mode_wrap.grid(row=0, column=1, sticky="w")
        graph_period_radios: list[ttk.Radiobutton] = []
        rb = ttk.Radiobutton(mode_wrap, text="5日", value="5d", variable=window_mode_var)
        rb.pack(side=tk.LEFT, padx=(0, 6))
        graph_period_radios.append(rb)
        rb = ttk.Radiobutton(mode_wrap, text="3日前寄せ", value="3d_left", variable=window_mode_var)
        rb.pack(side=tk.LEFT, padx=(0, 6))
        graph_period_radios.append(rb)
        rb = ttk.Radiobutton(mode_wrap, text="3日中央", value="3d_center", variable=window_mode_var)
        rb.pack(side=tk.LEFT, padx=(0, 6))
        graph_period_radios.append(rb)
        rb = ttk.Radiobutton(mode_wrap, text="3日後寄せ", value="3d_right", variable=window_mode_var)
        rb.pack(side=tk.LEFT)
        graph_period_radios.append(rb)

        panel = cls(
            parent=parent,
            frame=frame,
            input_zip_row=input_zip_row,
            period_input_mode_var=period_input_mode_var,
            window_mode_var=window_mode_var,
            date_listbox=date_listbox,
            candidate_count_var=candidate_count_var,
            selected_count_var=selected_count_var,
            refresh_button=refresh_button,
            import_excel_button=import_excel_button,
            graph_period_radios=graph_period_radios,
            zip_windows_cache={},
            period_start_entry=period_start_entry,
            period_end_entry=period_end_entry,
            period_row=period_row,
            graph_period_row=row_mode,
            period_input_mode_row=row_input_mode,
        )
        refresh_button.configure(
            command=lambda p=panel, v=input_zip_var: p.refresh_candidates(v.get().strip(), force=True)
        )
        import_excel_button.configure(command=lambda: on_import_excel() if on_import_excel is not None else None)
        date_listbox.bind(
            "<<ListboxSelect>>",
            lambda _e: (
                panel._update_selected_count(),
                on_change() if on_change is not None else None,
            ),
        )
        period_input_mode_var.trace_add(
            "write",
            lambda *_: (
                panel._update_auto_mode_state(),
                on_change() if on_change is not None else None,
            ),
        )
        window_mode_var.trace_add(
            "write",
            lambda *_: (
                panel.refresh_candidates(input_zip_var.get().strip(), force=False),
                on_change() if on_change is not None else None,
            ),
        )
        panel._update_auto_mode_state()
        return panel

    def _resolve_window(self, target_date: date, mode: str) -> tuple[datetime, datetime]:
        if mode == "5d":
            start = datetime.combine(target_date - timedelta(days=2), time(hour=0))
            end = datetime.combine(target_date + timedelta(days=2), time(hour=23))
            return start, end
        if mode == "3d_left":
            start = datetime.combine(target_date - timedelta(days=2), time(hour=0))
            end = datetime.combine(target_date, time(hour=23))
            return start, end
        if mode == "3d_center":
            start = datetime.combine(target_date - timedelta(days=1), time(hour=0))
            end = datetime.combine(target_date + timedelta(days=1), time(hour=23))
            return start, end
        if mode == "3d_right":
            start = datetime.combine(target_date, time(hour=0))
            end = datetime.combine(target_date + timedelta(days=2), time(hour=23))
            return start, end
        raise ValueError(f"未対応の窓位置です: {mode}")

    @staticmethod
    def _coverage_ok(*, windows: list[ZipWindow], window_start: datetime, window_end: datetime) -> bool:
        pointer = window_start
        for item in sorted(windows, key=lambda z: z.start_at):
            if item.end_at < pointer:
                continue
            if item.start_at > pointer:
                return False
            pointer = max(pointer, item.end_at + timedelta(hours=1))
            if pointer > window_end:
                return True
        return pointer > window_end

    def mark_zipdir_changed(self) -> None:
        self.date_listbox.delete(0, tk.END)
        self.candidate_count_var.set("候補日: 未更新（候補更新を押してください）")
        self._update_selected_count()

    def _load_zip_windows(self, input_zipdir: str, *, force: bool) -> list[ZipWindow]:
        key = str(Path(input_zipdir).resolve()) if input_zipdir else ""
        if key and not force and key in self.zip_windows_cache:
            return self.zip_windows_cache[key]
        windows = list_zip_windows(input_zipdir=Path(input_zipdir))
        if key:
            self.zip_windows_cache[key] = windows
        return windows

    def refresh_candidates(self, input_zipdir: str, *, force: bool = False) -> None:
        self.date_listbox.delete(0, tk.END)
        if not input_zipdir:
            self.candidate_count_var.set("候補日: 0件（入力ZIP未指定）")
            self._update_selected_count()
            return
        try:
            windows = self._load_zip_windows(input_zipdir, force=force)
        except Exception as exc:  # noqa: BLE001
            self.candidate_count_var.set(f"候補日: 0件（読込失敗: {exc}）")
            self._update_selected_count()
            return
        if not windows:
            self.candidate_count_var.set("候補日: 0件（ZIPなし）")
            self._update_selected_count()
            return

        min_day = min(item.start_at.date() for item in windows)
        max_day = max(item.end_at.date() for item in windows)
        mode = self.window_mode_var.get().strip() or "5d"
        candidates: list[str] = []
        d = min_day
        while d <= max_day:
            ws, we = self._resolve_window(d, mode)
            selected = [w for w in windows if w.start_at <= we and ws <= w.end_at]
            if selected and self._coverage_ok(windows=selected, window_start=ws, window_end=we):
                candidates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
        for item in candidates:
            self.date_listbox.insert(tk.END, item)
        if self.is_auto_mode() and candidates and self.date_listbox.curselection() == ():
            self.date_listbox.selection_set(0)
        self.candidate_count_var.set(f"候補日: {len(candidates)}件")
        self._update_selected_count()

    def get_window_mode(self) -> str:
        mode = self.window_mode_var.get().strip()
        return mode if mode in _WINDOW_MODE_LABELS else "5d"

    def get_window_mode_label(self) -> str:
        return _WINDOW_MODE_LABELS.get(self.get_window_mode(), "5日")

    def is_auto_mode(self) -> bool:
        return self.period_input_mode_var.get().strip() == "auto_dates"

    def _update_auto_mode_state(self) -> None:
        state = tk.NORMAL if self.is_auto_mode() else tk.DISABLED
        self.refresh_button.configure(state=state)
        self.import_excel_button.configure(state=state)
        self.date_listbox.configure(state=state)
        for rb in self.graph_period_radios:
            rb.configure(state=state)
        self.period_start_entry.configure(state=tk.DISABLED if self.is_auto_mode() else tk.NORMAL)
        self.period_end_entry.configure(state=tk.DISABLED if self.is_auto_mode() else tk.NORMAL)
        if self.is_auto_mode():
            if self.date_listbox.size() > 0 and self.date_listbox.curselection() == ():
                self.date_listbox.selection_set(0)
        else:
            self.date_listbox.selection_clear(0, tk.END)
        self._update_selected_count()

    def apply_target_dates(self, target_dates: list[date]) -> dict[str, object]:
        candidate_index: dict[str, int] = {}
        for i in range(self.date_listbox.size()):
            candidate_index[self.date_listbox.get(i).strip()] = i

        unique_dates = sorted({d for d in target_dates})
        requested = [d.strftime("%Y-%m-%d") for d in unique_dates]
        matched: list[str] = []
        unmatched: list[str] = []
        self.date_listbox.selection_clear(0, tk.END)
        for raw in requested:
            idx = candidate_index.get(raw)
            if idx is None:
                unmatched.append(raw)
                continue
            self.date_listbox.selection_set(idx)
            matched.append(raw)
        self._update_selected_count()
        return {
            "requested_count": len(requested),
            "matched_count": len(matched),
            "unmatched_count": len(unmatched),
            "matched_dates": matched,
            "unmatched_dates": unmatched,
        }

    def refresh_input_mode_state(self) -> None:
        self._update_auto_mode_state()

    def set_form_label_minsize(self, pixels: int) -> None:
        minsize = max(0, int(pixels))
        self.period_input_mode_row.columnconfigure(0, minsize=minsize)
        self.period_row.columnconfigure(0, minsize=minsize)
        self.graph_period_row.columnconfigure(0, minsize=minsize)

    def _update_selected_count(self) -> None:
        self.selected_count_var.set(f"選択中: {len(self.date_listbox.curselection())}件")

    def get_period_input_mode_label(self) -> str:
        mode = self.period_input_mode_var.get().strip()
        return _PERIOD_INPUT_MODE_LABELS.get(mode, "期間を直接指定")

    def get_selected_target_dates(self) -> list[date]:
        result: list[date] = []
        for idx in self.date_listbox.curselection():
            raw = self.date_listbox.get(idx).strip()
            try:
                result.append(datetime.strptime(raw, "%Y-%m-%d").date())
            except ValueError:
                continue
        return result

    def build_window_for_date(self, target_date: date) -> tuple[datetime, datetime, int]:
        mode = self.get_window_mode()
        start, end = self._resolve_window(target_date, mode)
        day_count = 5 if mode == "5d" else 3
        return start, end, day_count

    def build_window(self) -> tuple[date, datetime, datetime, int]:
        selected = self.get_selected_target_dates()
        target = selected[0] if selected else None
        if target is None:
            raise ValueError("解析雨量モードでは対象日を選択してください。")
        mode = self.get_window_mode()
        start, end = self._resolve_window(target, mode)
        day_count = 5 if mode == "5d" else 3
        return target, start, end, day_count

    def show(self, *, before: ttk.Frame | None = None) -> None:
        if before is not None:
            self.frame.pack(fill=tk.BOTH, expand=True, pady=0, before=before)
        else:
            self.frame.pack(fill=tk.BOTH, expand=True, pady=0)

    def hide(self) -> None:
        self.frame.pack_forget()
