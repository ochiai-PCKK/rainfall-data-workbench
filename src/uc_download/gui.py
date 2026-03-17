from __future__ import annotations

import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox
from tkinter import ttk

from .workflows import fetch_zips
from .workflows import ingest_mail_bodies


class UcDownloadGui:
    """メール本文貼り付けと ZIP 取得のための簡易 GUI。"""

    def __init__(
        self,
        *,
        output_dir: Path,
        downloads_dir: Path,
        expected_start: date | None = None,
        expected_end: date | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.downloads_dir = downloads_dir

        self.root = tk.Tk()
        self.root.title("UC ダウンロード補助")
        self.root.geometry("1100x760")

        self.expected_start_var = tk.StringVar(value=expected_start.isoformat() if expected_start else "")
        self.expected_end_var = tk.StringVar(value=expected_end.isoformat() if expected_end else "")
        self.allow_warnings_var = tk.BooleanVar(value=True)
        self.status_filter_var = tk.StringVar(value="pending")
        self.auto_watch_var = tk.BooleanVar(value=False)
        self.last_clipboard_text: str | None = None
        self.pending_auto_text: str | None = None
        self.is_busy = False

        self._build_layout()
        self._bind_shortcuts()
        self._schedule_clipboard_watch()

    def run(self) -> None:
        self.root.mainloop()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.root, padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(7, weight=1)

        ttk.Label(controls, text="期待開始日").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.expected_start_var, width=14).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(controls, text="期待終了日").grid(row=0, column=2, sticky="w")
        ttk.Entry(controls, textvariable=self.expected_end_var, width=14).grid(row=0, column=3, sticky="w", padx=(4, 12))
        ttk.Checkbutton(controls, text="warning を許容", variable=self.allow_warnings_var).grid(row=0, column=4, sticky="w", padx=(0, 12))
        ttk.Checkbutton(controls, text="自動監視", variable=self.auto_watch_var).grid(row=0, column=5, sticky="w", padx=(0, 12))
        ttk.Button(controls, text="クリップボード貼付 (Ctrl+Shift+V)", command=self._paste_clipboard).grid(row=0, column=6, sticky="w", padx=(0, 8))
        self.ingest_button = ttk.Button(controls, text="取り込み (Ctrl+Enter)", command=self._start_ingest)
        self.ingest_button.grid(row=0, column=7, sticky="w", padx=(0, 8))
        ttk.Button(controls, text="クリア (Ctrl+L)", command=self._clear_text).grid(row=0, column=8, sticky="w")

        body_frame = ttk.Panedwindow(self.root, orient="vertical")
        body_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        ingest_frame = ttk.Labelframe(body_frame, text="メール本文貼り付け", padding=8)
        ingest_frame.columnconfigure(0, weight=1)
        ingest_frame.rowconfigure(0, weight=1)
        self.mail_text = tk.Text(ingest_frame, wrap="word", undo=True)
        self.mail_text.grid(row=0, column=0, sticky="nsew")
        ingest_scroll = ttk.Scrollbar(ingest_frame, orient="vertical", command=self.mail_text.yview)
        ingest_scroll.grid(row=0, column=1, sticky="ns")
        self.mail_text.configure(yscrollcommand=ingest_scroll.set)
        body_frame.add(ingest_frame, weight=3)

        result_frame = ttk.Labelframe(body_frame, text="実行結果", padding=8)
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(1, weight=1)

        top_row = ttk.Frame(result_frame)
        top_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(top_row, text="ZIP 取得対象").pack(side="left")
        ttk.Combobox(
            top_row,
            textvariable=self.status_filter_var,
            state="readonly",
            values=("pending", "failed", "expired", "all"),
            width=10,
        ).pack(side="left", padx=(6, 8))
        self.fetch_button = ttk.Button(top_row, text="ZIP取得 (F5)", command=self._start_fetch)
        self.fetch_button.pack(side="left")
        self.status_label = ttk.Label(top_row, text="待機中")
        self.status_label.pack(side="left", padx=(12, 0))

        self.result_text = tk.Text(result_frame, wrap="word", height=18, state="disabled")
        self.result_text.grid(row=1, column=0, sticky="nsew")
        result_scroll = ttk.Scrollbar(result_frame, orient="vertical", command=self.result_text.yview)
        result_scroll.grid(row=1, column=1, sticky="ns")
        self.result_text.configure(yscrollcommand=result_scroll.set)
        body_frame.add(result_frame, weight=2)

    def _paste_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showerror("クリップボード", "クリップボードから文字列を取得できませんでした。")
            return
        self._set_mail_text(text)

    def _clear_text(self) -> None:
        self.mail_text.delete("1.0", tk.END)

    def _start_ingest(self, *, clear_on_success: bool = False) -> None:
        text = self.mail_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("取り込み", "メール本文を貼り付けてください。")
            return

        try:
            expected_start = self._parse_optional_date(self.expected_start_var.get())
            expected_end = self._parse_optional_date(self.expected_end_var.get())
        except ValueError as exc:
            messagebox.showerror("日付形式", str(exc))
            return

        self._set_busy(True, "取り込み中")

        def worker() -> None:
            try:
                summary = ingest_mail_bodies(
                    text,
                    output_dir=self.output_dir,
                    expected_start=expected_start,
                    expected_end=expected_end,
                )
            except Exception as exc:  # pragma: no cover - GUI runtime path
                self.root.after(0, lambda: self._handle_error("取り込み", exc))
                return
            self.root.after(0, lambda: self._finish_ingest(summary, clear_on_success=clear_on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _start_fetch(self) -> None:
        self._set_busy(True, "ZIP取得中")
        status_filter = self.status_filter_var.get()

        def worker() -> None:
            try:
                summary = fetch_zips(
                    output_dir=self.output_dir,
                    downloads_dir=self.downloads_dir,
                    status_filter=status_filter,
                )
            except Exception as exc:  # pragma: no cover - GUI runtime path
                self.root.after(0, lambda: self._handle_error("ZIP取得", exc))
                return
            self.root.after(0, lambda: self._finish_fetch(summary))

        threading.Thread(target=worker, daemon=True).start()

    def _ingest_and_fetch(self, *, clear_on_success: bool = False) -> None:
        """取り込み成功後に pending ZIP を続けて取得する。"""
        text = self.mail_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("取り込み", "メール本文を貼り付けてください。")
            return
        try:
            expected_start = self._parse_optional_date(self.expected_start_var.get())
            expected_end = self._parse_optional_date(self.expected_end_var.get())
        except ValueError as exc:
            messagebox.showerror("日付形式", str(exc))
            return

        self._set_busy(True, "取り込みとZIP取得中")

        def worker() -> None:
            try:
                ingest_summary = ingest_mail_bodies(
                    text,
                    output_dir=self.output_dir,
                    expected_start=expected_start,
                    expected_end=expected_end,
                )
                warning_count = int(ingest_summary["warning_count"])
                if warning_count > 0 and not self.allow_warnings_var.get():
                    self.root.after(
                        0,
                        lambda: self._finish_ingest_only(
                            ingest_summary,
                            warn_blocked=True,
                            clear_on_success=False,
                        ),
                    )
                    return
                fetch_summary = fetch_zips(
                    output_dir=self.output_dir,
                    downloads_dir=self.downloads_dir,
                    status_filter="pending",
                )
            except Exception as exc:  # pragma: no cover - GUI runtime path
                self.root.after(0, lambda: self._handle_error("取り込み/ZIP取得", exc))
                return
            self.root.after(
                0,
                lambda: self._finish_ingest_then_fetch(
                    ingest_summary,
                    fetch_summary,
                    clear_on_success=clear_on_success,
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_ingest(self, summary: dict[str, object], *, clear_on_success: bool) -> None:
        self._finish_ingest_only(summary, warn_blocked=False, clear_on_success=clear_on_success)

    def _finish_ingest_only(
        self,
        summary: dict[str, object],
        *,
        warn_blocked: bool,
        clear_on_success: bool,
    ) -> None:
        lines = [
            "[取り込み結果]",
            f"added={summary['added_entry_count']}",
            f"refreshed={summary.get('refreshed_entry_count', 0)}",
            f"duplicates={summary['duplicate_count']}",
            f"parse_failed={summary['parse_failure_count']}",
            f"warnings={summary['warning_count']}",
            f"summary_path={summary['summary_path']}",
        ]
        warning_examples = summary.get("warning_examples")
        if isinstance(warning_examples, list) and warning_examples:
            lines.append("")
            lines.append("[warning 全件]")
            for item in warning_examples:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('issue_type')}: {item.get('message')}")

        refreshed_entries = summary.get("refreshed_entries")
        if isinstance(refreshed_entries, list) and refreshed_entries:
            lines.append("")
            lines.append("[差し替え]")
            for item in refreshed_entries[:3]:
                if isinstance(item, dict):
                    lines.append(
                        f"- {item.get('period_start')}..{item.get('period_end')} "
                        f"{item.get('old_source_id')} -> {item.get('new_source_id')}"
                    )

        self._append_result("\n".join(lines))
        if clear_on_success:
            self._clear_text()
            self.mail_text.focus_set()
        self._set_busy(False, "待機中")
        if warn_blocked or (int(summary["warning_count"]) > 0 and not self.allow_warnings_var.get()):
            messagebox.showwarning("取り込み完了", "warning があります。結果欄を確認してください。")

    def _finish_fetch(self, summary: dict[str, object]) -> None:
        lines = [
            "[ZIP取得結果]",
            f"target={summary['target_entry_count']}",
            f"downloaded={summary['downloaded_count']}",
            f"already_exists={summary['already_exists_count']}",
            f"expired={summary['expired_count']}",
            f"failed={summary['failed_count']}",
            f"summary_path={summary['summary_path']}",
        ]
        examples = summary.get("result_examples")
        if isinstance(examples, list) and examples:
            lines.append("")
            lines.append("[代表例]")
            for item in examples[:3]:
                if isinstance(item, dict):
                    lines.append(
                        f"- {item.get('period_start')}..{item.get('period_end')} "
                        f"{item.get('status')}: {item.get('message')}"
                    )
        self._append_result("\n".join(lines))
        self._set_busy(False, "待機中")

    def _finish_ingest_then_fetch(
        self,
        ingest_summary: dict[str, object],
        fetch_summary: dict[str, object],
        *,
        clear_on_success: bool,
    ) -> None:
        self._finish_ingest_only(ingest_summary, warn_blocked=False, clear_on_success=clear_on_success)
        self._finish_fetch(fetch_summary)

    def _handle_error(self, label: str, exc: Exception) -> None:
        self._append_result(f"[{label}エラー]\n{exc}")
        self._set_busy(False, "待機中")
        messagebox.showerror(label, str(exc))

    def _append_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        if self.result_text.index("end-1c") != "1.0":
            self.result_text.insert(tk.END, "\n\n")
        self.result_text.insert(tk.END, text)
        self.result_text.see(tk.END)
        self.result_text.configure(state="disabled")

    def _set_busy(self, busy: bool, status: str) -> None:
        self.is_busy = busy
        state = "disabled" if busy else "normal"
        self.ingest_button.configure(state=state)
        self.fetch_button.configure(state=state)
        self.status_label.configure(text=status)
        if not busy and self.pending_auto_text:
            next_text = self.pending_auto_text
            self.pending_auto_text = None
            self.root.after(0, lambda: self._run_auto_ingest(next_text))

    def _parse_optional_date(self, value: str) -> date | None:
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return date.fromisoformat(stripped)
        except ValueError as exc:
            raise ValueError(f"日付は YYYY-MM-DD 形式で入力してください: {value}") from exc

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-Return>", lambda event: self._start_ingest(clear_on_success=True))
        self.root.bind("<Control-KP_Enter>", lambda event: self._start_ingest(clear_on_success=True))
        self.root.bind("<Control-Shift-Return>", lambda event: self._ingest_and_fetch(clear_on_success=True))
        self.root.bind("<Control-Shift-KP_Enter>", lambda event: self._ingest_and_fetch(clear_on_success=True))
        self.root.bind("<F5>", lambda event: self._start_fetch())
        self.root.bind("<Control-l>", lambda event: self._clear_text())
        self.root.bind("<Control-L>", lambda event: self._clear_text())
        self.root.bind("<Control-Shift-V>", lambda event: self._paste_clipboard())

    def _schedule_clipboard_watch(self) -> None:
        self.root.after(1000, self._poll_clipboard)

    def _poll_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self._schedule_clipboard_watch()
            return

        if self.auto_watch_var.get() and isinstance(text, str):
            normalized = text.strip()
            if normalized and normalized != self.last_clipboard_text and self._looks_like_uc_mail(normalized):
                self.last_clipboard_text = normalized
                if self.is_busy:
                    self.pending_auto_text = normalized
                else:
                    self._run_auto_ingest(normalized)
            elif normalized:
                self.last_clipboard_text = normalized

        self._schedule_clipboard_watch()

    def _run_auto_ingest(self, text: str) -> None:
        self._set_mail_text(text)
        self.status_label.configure(text="自動取り込み待機")
        self._ingest_and_fetch(clear_on_success=True)

    def _set_mail_text(self, text: str) -> None:
        self.mail_text.delete("1.0", tk.END)
        self.mail_text.insert("1.0", text)
        self.mail_text.focus_set()

    def _looks_like_uc_mail(self, text: str) -> bool:
        return "データ期間" in text and "ucrain.i-ric.info/download/" in text


def launch_gui(
    *,
    output_dir: Path,
    downloads_dir: Path,
    expected_start: date | None = None,
    expected_end: date | None = None,
) -> None:
    """簡易 GUI を起動する。"""
    app = UcDownloadGui(
        output_dir=output_dir,
        downloads_dir=downloads_dir,
        expected_start=expected_start,
        expected_end=expected_end,
    )
    app.run()
