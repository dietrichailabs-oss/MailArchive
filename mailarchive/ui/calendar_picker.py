from __future__ import annotations

import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk

from mailarchive.ui.date_ranges import format_user_date, parse_user_date


MONTH_NAMES = tuple(calendar.month_name[1:])


def month_cells(year: int, month: int) -> list[list[int]]:
    """Return a Sunday-first month grid; zeroes represent padding cells."""
    return calendar.Calendar(firstweekday=6).monthdayscalendar(int(year), int(month))


class CalendarPopup(tk.Toplevel):
    """Small dependency-free Tk calendar used for Start/End date selection."""

    def __init__(self, parent, target_var: tk.StringVar, *, title: str = 'Select date', on_select=None):
        super().__init__(parent)
        self.target_var = target_var
        self.on_select = on_select
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)

        initial = date.today()
        try:
            iso = parse_user_date(target_var.get(), label='date')
            if iso:
                initial = date.fromisoformat(iso)
        except ValueError:
            pass
        self.selected = initial if target_var.get().strip() else None

        self.year_var = tk.StringVar(value=str(initial.year))
        self.month_var = tk.StringVar(value=calendar.month_name[initial.month])

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill='both', expand=True)

        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=(0, 8))
        ttk.Button(controls, text='‹', width=3, command=lambda: self._shift_month(-1)).pack(side='left')

        today = date.today()
        years = [str(y) for y in range(1900, today.year + 21)]
        year_box = ttk.Combobox(controls, textvariable=self.year_var, values=years, state='readonly', width=7)
        year_box.pack(side='left', padx=(6, 4))
        month_box = ttk.Combobox(controls, textvariable=self.month_var, values=MONTH_NAMES, state='readonly', width=11)
        month_box.pack(side='left', padx=4)
        ttk.Button(controls, text='›', width=3, command=lambda: self._shift_month(1)).pack(side='left', padx=(4, 0))

        year_box.bind('<<ComboboxSelected>>', lambda _event: self._draw_days())
        month_box.bind('<<ComboboxSelected>>', lambda _event: self._draw_days())

        self.days_frame = ttk.Frame(outer)
        self.days_frame.pack()
        self._draw_days()

        footer = ttk.Frame(outer)
        footer.pack(fill='x', pady=(10, 0))
        ttk.Button(footer, text='Today', command=self._choose_today).pack(side='left')
        ttk.Button(footer, text='Cancel', command=self.destroy).pack(side='right')

        self.bind('<Escape>', lambda _event: self.destroy())
        self.grab_set()
        self.update_idletasks()
        try:
            x = parent.winfo_rootx() + max(30, (parent.winfo_width() - self.winfo_width()) // 2)
            y = parent.winfo_rooty() + max(30, (parent.winfo_height() - self.winfo_height()) // 3)
            self.geometry(f'+{x}+{y}')
        except tk.TclError:
            pass
        self.focus_set()

    def _year_month(self) -> tuple[int, int]:
        year = int(self.year_var.get())
        month = MONTH_NAMES.index(self.month_var.get()) + 1
        return year, month

    def _shift_month(self, delta: int) -> None:
        year, month = self._year_month()
        total = year * 12 + (month - 1) + int(delta)
        new_year, month0 = divmod(total, 12)
        if not 1900 <= new_year <= date.today().year + 20:
            return
        self.year_var.set(str(new_year))
        self.month_var.set(calendar.month_name[month0 + 1])
        self._draw_days()

    def _draw_days(self) -> None:
        for child in self.days_frame.winfo_children():
            child.destroy()
        for col, label in enumerate(('Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat')):
            ttk.Label(self.days_frame, text=label, width=4, anchor='center').grid(row=0, column=col, padx=1, pady=(0, 3))

        year, month = self._year_month()
        for row_index, week in enumerate(month_cells(year, month), start=1):
            for col, day in enumerate(week):
                if not day:
                    ttk.Label(self.days_frame, text='', width=4).grid(row=row_index, column=col, padx=1, pady=1)
                    continue
                chosen = bool(self.selected and self.selected.year == year and self.selected.month == month and self.selected.day == day)
                button = tk.Button(
                    self.days_frame,
                    text=str(day),
                    width=3,
                    relief='sunken' if chosen else 'raised',
                    borderwidth=3 if chosen else 1,
                    font=('Segoe UI', 9, 'bold' if chosen else 'normal'),
                    command=lambda d=day: self._choose_day(d),
                    takefocus=True,
                )
                button.grid(row=row_index, column=col, padx=1, pady=1)

    def _choose_day(self, day: int) -> None:
        year, month = self._year_month()
        selected = date(year, month, int(day))
        self.selected = selected
        self.target_var.set(format_user_date(selected))
        if self.on_select:
            self.on_select(selected)
        self.destroy()

    def _choose_today(self) -> None:
        selected = date.today()
        self.selected = selected
        self.target_var.set(format_user_date(selected))
        if self.on_select:
            self.on_select(selected)
        self.destroy()
