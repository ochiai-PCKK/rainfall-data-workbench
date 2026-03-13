from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk
from collections.abc import Callable


RegisterFn = Callable[[str, tk.Widget, str, str], None]


def add_labeled_entry(
    parent: ttk.Frame,
    *,
    row: int,
    label_text: str,
    variable: tk.StringVar,
    entry_widget_id: str,
    register_widget: RegisterFn,
    columnspan: int = 1,
    width: int = 56,
) -> ttk.Entry:
    """ラベル付き Entry を 1 行追加する。"""
    label = ttk.Label(parent, text=label_text)
    label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
    register_widget(f"label.{entry_widget_id}", label, "label", label_text)

    entry = ttk.Entry(parent, textvariable=variable, width=width)
    entry.grid(row=row, column=1, columnspan=columnspan, sticky="ew", padx=(0, 8), pady=2)
    register_widget(entry_widget_id, entry, "entry", label_text)
    return entry


def add_labeled_combobox(
    parent: ttk.Frame,
    *,
    row: int,
    label_text: str,
    variable: tk.StringVar,
    values: list[str],
    widget_id: str,
    register_widget: RegisterFn,
    width: int = 28,
    state: str = "readonly",
) -> ttk.Combobox:
    """ラベル付き Combobox を 1 行追加する。"""
    label = ttk.Label(parent, text=label_text)
    label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
    register_widget(f"label.{widget_id}", label, "label", label_text)

    combo = ttk.Combobox(parent, textvariable=variable, values=values, width=width, state=state)
    combo.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=2)
    register_widget(widget_id, combo, "combobox", label_text)
    return combo


def add_labeled_text(
    parent: ttk.Frame,
    *,
    row: int,
    label_text: str,
    widget_id: str,
    register_widget: RegisterFn,
    height: int = 4,
    width: int = 72,
) -> tk.Text:
    """ラベル付き複数行 Text を追加する。"""
    label = ttk.Label(parent, text=label_text)
    label.grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
    register_widget(f"label.{widget_id}", label, "label", label_text)

    text = tk.Text(parent, height=height, width=width, wrap="none")
    text.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=4)
    register_widget(widget_id, text, "text", label_text)
    return text


def add_scrolled_log(
    parent: ttk.Frame,
    *,
    widget_id: str,
    register_widget: RegisterFn,
    height: int = 14,
) -> scrolledtext.ScrolledText:
    """スクロール付きログテキストを追加する。"""
    text = scrolledtext.ScrolledText(parent, height=height, wrap="word")
    text.grid(row=0, column=0, sticky="nsew")
    register_widget(widget_id, text, "log", "実行ログ")
    return text
