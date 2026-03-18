from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from datetime import timedelta
from tkinter import ttk
from typing import Callable

import pandas as pd
from openpyxl import load_workbook

_DATE_SHEET_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_RESPLIT_PREFIX = "【再分割】"
_SPAN_LABELS = {
    "5d": "5日",
    "3d_left": "3日前寄せ",
    "3d_center": "3日中央",
    "3d_right": "3日後寄せ",
}


@dataclass
class ExcelModePanel:
    parent: tk.Misc
    frame: ttk.Frame
    input_excel_row: ttk.Frame
    span_var: tk.StringVar
    sheet_listbox: tk.Listbox
    sheet_count_var: tk.StringVar
    selected_count_var: tk.StringVar
    span_row: ttk.Frame

    @classmethod
    def create(
        cls,
        parent: tk.Misc,
        *,
        build_path_row: Callable[..., ttk.Frame],
        input_excel_var: tk.StringVar,
    ) -> "ExcelModePanel":
        frame = ttk.Frame(parent)
        span_var = tk.StringVar(value="5d")
        input_excel_row = build_path_row(
            frame,
            "入力Excelファイル",
            input_excel_var,
            ask_file=True,
            filetypes=[("Excel", "*.xlsx;*.xls"), ("すべて", "*.*")],
        )

        opt_row = ttk.Frame(frame)
        opt_row.pack(fill=tk.X, pady=(2, 4))
        opt_row.columnconfigure(1, weight=1)
        ttk.Label(opt_row, text="グラフ期間").grid(row=0, column=0, sticky="w", padx=(0, 6))
        span_wrap = ttk.Frame(opt_row)
        span_wrap.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(span_wrap, text="5日", value="5d", variable=span_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(span_wrap, text="3日前寄せ", value="3d_left", variable=span_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(span_wrap, text="3日中央", value="3d_center", variable=span_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(span_wrap, text="3日後寄せ", value="3d_right", variable=span_var).pack(side=tk.LEFT)

        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(toolbar, text="イベント候補（複数選択可）", width=22).pack(side=tk.LEFT)
        ttk.Button(
            toolbar,
            text="候補更新",
            command=lambda: None,  # 差し替え
            width=8,
        ).pack(side=tk.RIGHT)

        list_wrap = ttk.Frame(frame)
        list_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 2))
        sheet_listbox = tk.Listbox(list_wrap, selectmode=tk.EXTENDED, height=10, exportselection=False)
        sheet_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL, command=sheet_listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        sheet_listbox.configure(yscrollcommand=scroll.set)
        sheet_count_var = tk.StringVar(value="候補: 0件")
        selected_count_var = tk.StringVar(value="選択中: 0件")
        count_row = ttk.Frame(frame)
        count_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(count_row, textvariable=sheet_count_var).pack(side=tk.LEFT)
        ttk.Label(count_row, textvariable=selected_count_var).pack(side=tk.RIGHT)

        panel = cls(
            parent=parent,
            frame=frame,
            input_excel_row=input_excel_row,
            span_var=span_var,
            sheet_listbox=sheet_listbox,
            sheet_count_var=sheet_count_var,
            selected_count_var=selected_count_var,
            span_row=opt_row,
        )
        # 候補更新ボタンに実関数を接続
        for child in toolbar.winfo_children():
            if isinstance(child, ttk.Button):
                child.configure(command=lambda p=panel, v=input_excel_var: p.refresh_candidates(v.get().strip()))
        sheet_listbox.bind("<<ListboxSelect>>", lambda _e: panel._update_selected_count())
        return panel

    def show(self, *, before: ttk.Frame | None = None) -> None:
        if before is not None:
            self.frame.pack(fill=tk.BOTH, expand=True, pady=0, before=before)
        else:
            self.frame.pack(fill=tk.BOTH, expand=True, pady=0)

    def hide(self) -> None:
        self.frame.pack_forget()

    def refresh_candidates(self, excel_path: str) -> None:
        self.sheet_listbox.delete(0, tk.END)
        if not excel_path:
            self.sheet_count_var.set("候補: 0件（Excel未指定）")
            self._update_selected_count()
            return
        path = excel_path.strip()
        try:
            wb = load_workbook(path, data_only=True, read_only=True)
        except Exception as exc:  # noqa: BLE001
            self.sheet_count_var.set(f"候補: 0件（読込失敗: {exc}）")
            self._update_selected_count()
            return
        candidates: list[str] = []
        for name in wb.sheetnames:
            if _DATE_SHEET_RE.fullmatch(name):
                candidates.append(name)
                continue
            if name.startswith(_RESPLIT_PREFIX):
                base = name.replace(_RESPLIT_PREFIX, "", 1)
                if _DATE_SHEET_RE.fullmatch(base):
                    candidates.append(name)
        for item in candidates:
            self.sheet_listbox.insert(tk.END, item)
        self.sheet_count_var.set(f"候補: {len(candidates)}件")
        self._update_selected_count()

    def _update_selected_count(self) -> None:
        self.selected_count_var.set(f"選択中: {len(self.sheet_listbox.curselection())}件")

    def get_selected_sheet_names(self) -> list[str]:
        return [self.sheet_listbox.get(i) for i in self.sheet_listbox.curselection()]

    def get_span(self) -> str:
        value = self.span_var.get().strip()
        return value if value in _SPAN_LABELS else "5d"

    def get_span_label(self) -> str:
        return _SPAN_LABELS.get(self.get_span(), "5日")

    def get_preview_span(self) -> str:
        return "5d" if self.get_span() == "5d" else "3d"

    def set_form_label_minsize(self, pixels: int) -> None:
        minsize = max(0, int(pixels))
        self.span_row.columnconfigure(0, minsize=minsize)

    def build_preview_frame(self, excel_path: str) -> pd.DataFrame | None:
        selected = self.get_selected_sheet_names()
        if not selected:
            return None
        path = excel_path.strip()
        if not path:
            return None
        target = selected[0]
        wb = load_workbook(path, data_only=True, read_only=True)
        if target not in wb.sheetnames:
            return None
        ws = wb[target]
        observed: list[object] = []
        rainfall: list[object] = []
        for r in ws.iter_rows(min_row=5, max_col=17, values_only=True):
            # B列(index=1), Q列(index=16)
            b = r[1] if len(r) > 1 else None
            q = r[16] if len(r) > 16 else None
            if b is None and q is None:
                continue
            observed.append(b)
            rainfall.append(q)
        frame = pd.DataFrame({"observed_at": pd.to_datetime(observed, errors="coerce"), "rainfall_mm": rainfall})
        frame = frame.dropna(subset=["observed_at", "rainfall_mm"]).copy()
        frame["rainfall_mm"] = pd.to_numeric(frame["rainfall_mm"], errors="coerce")
        frame = frame.dropna(subset=["rainfall_mm"]).sort_values("observed_at").reset_index(drop=True)
        # Excel入力（01:00〜翌00:00）を本実行と同じ0時起点へ正規化する。
        frame["observed_at"] = frame["observed_at"] - timedelta(hours=1)
        span = self.get_preview_span()
        if span == "3d" and len(frame) >= 72:
            start_idx = max(0, (len(frame) - 72) // 2)
            frame = frame.iloc[start_idx : start_idx + 72].copy()
        elif span == "5d" and len(frame) >= 120:
            start_idx = max(0, (len(frame) - 120) // 2)
            frame = frame.iloc[start_idx : start_idx + 120].copy()
        return frame
