from __future__ import annotations

from pathlib import Path
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

from mailarchive.application.controller import ArchiveSelection
from mailarchive.archive.planning import resolve_archive_root
from mailarchive.configuration.settings import default_archive_parent
from mailarchive.ui.calendar_picker import CalendarPopup
from mailarchive.ui.date_ranges import PRESETS, format_user_date, resolve_date_range
from mailarchive.ui.formatting import format_account_identity, format_bytes
from mailarchive.ui.main_window.app import MailArchiveApp as BaseMailArchiveApp


def build_folder_display_rows(folder_rows: list[dict]) -> list[tuple[dict, str]]:
    """Return every visible folder with deterministic parent indentation."""
    visible = [row for row in folder_rows if not bool(row.get('hidden'))]
    by_id = {str(row.get('id')): row for row in visible if row.get('id')}

    def depth_for(row: dict) -> int:
        depth = 0
        current = str(row.get('parent_id') or '')
        seen: set[str] = set()
        while current and current in by_id and current not in seen and depth < 20:
            seen.add(current)
            depth += 1
            current = str(by_id[current].get('parent_id') or '')
        return depth

    rendered: list[tuple[dict, str]] = []
    for row in visible:
        depth = depth_for(row)
        name = str(row.get('name') or row.get('id') or '(unnamed)')
        prefix = ('    ' * depth) + ('↳ ' if depth else '')
        rendered.append((row, prefix + name))
    return rendered


class RC2MailArchiveApp(BaseMailArchiveApp):
    """RC2 user-facing wizard improvements layered on the QA-passed RC1 core."""

    def __init__(self, provider_session, settings_store, registry):
        self._selected_folder_ids_state: tuple[str, ...] = ()
        self._selected_folder_names_state: tuple[str, ...] = ()
        self._folder_selection_initialized = False
        self._date_preset_state = 'Older than 1 year'
        self._custom_start_state = ''
        self._custom_end_state = ''
        self._destination_state = ''
        super().__init__(provider_session, settings_store, registry)

    def _reset_wizard_state(self) -> None:
        self._selected_folder_ids_state = ()
        self._selected_folder_names_state = ()
        self._folder_selection_initialized = False
        self._date_preset_state = 'Older than 1 year'
        self._custom_start_state = ''
        self._custom_end_state = ''
        self._destination_state = ''
        for name in ('date_start', 'date_end'):
            if hasattr(self, name):
                delattr(self, name)
        self.selection = None
        self.current_archive = None
        self.last_archive_result = None

    def show_welcome(self):
        if self.provider is not None and self.controller is not None:
            return self.show_signed_in_home()
        self._clear()
        self._title(
            'Archive Microsoft 365 mail locally',
            'Your archive stays local and remains readable without Outlook or an internet connection.',
        )
        card = ttk.LabelFrame(self.body, text='Microsoft account', padding=18)
        card.pack(fill='x', pady=10)
        ttk.Label(
            card,
            text='MailArchive uses Microsoft’s sign-in window. Your Microsoft password is never entered into MailArchive.',
            wraplength=760,
        ).pack(anchor='w')
        ttk.Button(card, text='Sign in to Microsoft 365', command=self._sign_in).pack(anchor='w', pady=(14, 0))
        actions = ttk.Frame(self.body)
        actions.pack(fill='x', pady=20)
        ttk.Button(actions, text='Existing Archives', command=self.show_archive_manager).pack(side='left')
        ttk.Button(actions, text='Settings', command=self.show_settings).pack(side='left', padx=8)

    def show_signed_in_home(self):
        self._clear()
        metadata = {}
        try:
            metadata = self.provider.get_account_metadata() if self.provider else {}
        except Exception:
            metadata = {}
        identity = format_account_identity(metadata)
        self._title(
            'Microsoft 365 account connected',
            'You stay signed in while moving through MailArchive. Sign out only when you explicitly choose to.',
        )
        card = ttk.LabelFrame(self.body, text='Current session', padding=18)
        card.pack(fill='x', pady=10)
        ttk.Label(card, text=identity, font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        ttk.Button(card, text='Choose Mail Folders', command=self.show_folders).pack(anchor='w', pady=(14, 0))

        actions = ttk.Frame(self.body)
        actions.pack(fill='x', pady=20)
        ttk.Button(actions, text='Existing Archives', command=self.show_archive_manager).pack(side='left')
        ttk.Button(actions, text='Settings', command=self.show_settings).pack(side='left', padx=8)
        ttk.Button(actions, text='Sign Out', command=self._sign_out).pack(side='right')

    def show_folders(self):
        self._clear()
        self._title(
            'Choose folders',
            'All non-hidden Microsoft 365 mail folders returned for this account are shown. Select any combination or use Select all folders.',
        )

        toolbar = ttk.Frame(self.body)
        toolbar.pack(fill='x', pady=(0, 8))
        ttk.Button(toolbar, text='Select all folders', command=self._select_all_folders).pack(side='left')
        ttk.Button(toolbar, text='Clear all', command=self._clear_all_folders).pack(side='left', padx=(8, 0))
        self.folder_count_text = tk.StringVar(value='0 selected')
        ttk.Label(toolbar, textvariable=self.folder_count_text).pack(side='right')

        list_frame = ttk.Frame(self.body)
        list_frame.pack(fill='both', expand=True)
        self.folder_list = tk.Listbox(list_frame, selectmode='extended', height=18, exportselection=False)
        vertical = ttk.Scrollbar(list_frame, orient='vertical', command=self.folder_list.yview)
        horizontal = ttk.Scrollbar(list_frame, orient='horizontal', command=self.folder_list.xview)
        self.folder_list.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.folder_list.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self._folder_display_rows = build_folder_display_rows(self.folder_rows)
        if not self._folder_selection_initialized:
            self._selected_folder_ids_state = tuple(self.settings.preferred_folder_ids)
            self._folder_selection_initialized = True
        wanted = set(self._selected_folder_ids_state)
        for index, (row, label) in enumerate(self._folder_display_rows):
            self.folder_list.insert('end', label)
            if str(row.get('id')) in wanted:
                self.folder_list.selection_set(index)
        self.folder_list.bind('<<ListboxSelect>>', lambda _event: self._refresh_folder_count())
        self._refresh_folder_count()

        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=14)
        ttk.Button(buttons, text='Back', command=self._back_to_signed_home_from_folders).pack(side='left')
        ttk.Button(buttons, text='Next: Date Range', command=self._go_date_range).pack(side='right')

    def _refresh_folder_count(self) -> None:
        if not hasattr(self, 'folder_count_text') or not hasattr(self, 'folder_list'):
            return
        selected = len(self.folder_list.curselection())
        total = len(getattr(self, '_folder_display_rows', ()))
        self.folder_count_text.set(f'{selected} of {total} selected')

    def _select_all_folders(self) -> None:
        if self.folder_list.size():
            self.folder_list.selection_set(0, 'end')
        self._refresh_folder_count()

    def _clear_all_folders(self) -> None:
        self.folder_list.selection_clear(0, 'end')
        self._refresh_folder_count()

    def _capture_folder_selection(self, *, warn: bool = True) -> bool:
        selected = list(self.folder_list.curselection())
        if not selected:
            if warn:
                messagebox.showwarning('Select folders', 'Select at least one mailbox folder.')
                return False
            self._selected_folder_ids_state = ()
            self._selected_folder_names_state = ()
            self._folder_selection_initialized = True
            self.selected_folder_ids = ()
            self.selected_folder_names = ()
            return True
        rows = [self._folder_display_rows[i][0] for i in selected]
        self._selected_folder_ids_state = tuple(str(row['id']) for row in rows)
        self._selected_folder_names_state = tuple(str(row.get('name') or row['id']) for row in rows)
        self._folder_selection_initialized = True
        self.selected_folder_ids = self._selected_folder_ids_state
        self.selected_folder_names = self._selected_folder_names_state
        return True

    def _back_to_signed_home_from_folders(self) -> None:
        self._capture_folder_selection(warn=False)
        self.show_signed_in_home()

    def _go_date_range(self) -> None:
        if self._capture_folder_selection():
            self.show_date_range()

    def show_date_range(self):
        if not self._selected_folder_ids_state:
            messagebox.showwarning('Select folders', 'Select at least one mailbox folder.')
            self.show_folders()
            return
        self._clear()
        self._title('Choose date range', 'Boundary dates are inclusive. Dates are shown as month/day/year.')

        self.preset = tk.StringVar(value=self._date_preset_state)
        ttk.Label(self.body, text='Preset').pack(anchor='w')
        combo = ttk.Combobox(self.body, values=PRESETS, textvariable=self.preset, state='readonly', width=32)
        combo.pack(anchor='w', pady=(4, 14))

        grid = ttk.Frame(self.body)
        grid.pack(anchor='w')
        ttk.Label(grid, text='Custom start (MM/DD/YYYY)').grid(row=0, column=0, sticky='w')
        ttk.Label(grid, text='Custom end (MM/DD/YYYY)').grid(row=0, column=2, sticky='w', padx=(18, 0))

        self.start_var = tk.StringVar(value=self._custom_start_state)
        self.end_var = tk.StringVar(value=self._custom_end_state)
        self.start_entry = ttk.Entry(grid, textvariable=self.start_var, width=18)
        self.end_entry = ttk.Entry(grid, textvariable=self.end_var, width=18)
        self.start_entry.grid(row=1, column=0, pady=4)
        ttk.Button(
            grid,
            text='Calendar…',
            width=10,
            command=lambda: self._open_calendar(self.start_var, 'Select start date'),
        ).grid(row=1, column=1, padx=(5, 0), pady=4)
        self.end_entry.grid(row=1, column=2, padx=(18, 0), pady=4)
        ttk.Button(
            grid,
            text='Calendar…',
            width=10,
            command=lambda: self._open_calendar(self.end_var, 'Select end date'),
        ).grid(row=1, column=3, padx=(5, 0), pady=4)

        ttk.Label(
            self.body,
            text='Tip: choose Custom and use the calendar buttons to pick the year, month, and highlighted day.',
            wraplength=760,
        ).pack(anchor='w', pady=(8, 0))

        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=20)
        ttk.Button(buttons, text='Back', command=self._back_to_folders_from_date).pack(side='left')
        ttk.Button(buttons, text='Next: Destination', command=self._go_destination).pack(side='right')

    def _open_calendar(self, target_var: tk.StringVar, title: str) -> None:
        self.preset.set('Custom')
        CalendarPopup(self, target_var, title=title, on_select=lambda _chosen: self.preset.set('Custom'))

    def _capture_date_state(self) -> None:
        self._date_preset_state = self.preset.get()
        self._custom_start_state = self.start_var.get().strip()
        self._custom_end_state = self.end_var.get().strip()

    def _back_to_folders_from_date(self) -> None:
        self._capture_date_state()
        self.show_folders()

    def _go_destination(self) -> None:
        self._capture_date_state()
        try:
            self.date_start, self.date_end = resolve_date_range(
                self._date_preset_state,
                custom_start=self._custom_start_state,
                custom_end=self._custom_end_state,
            )
        except ValueError as exc:
            messagebox.showerror('Date range', str(exc))
            return
        self.show_destination()

    def show_destination(self):
        if not hasattr(self, 'date_start') or not hasattr(self, 'date_end'):
            try:
                self.date_start, self.date_end = resolve_date_range(
                    self._date_preset_state,
                    custom_start=self._custom_start_state,
                    custom_end=self._custom_end_state,
                )
            except ValueError:
                self.show_date_range()
                return
        self._clear()
        self._title(
            'Choose archive parent folder',
            'MailArchive creates a date-range archive folder here. The archive uses relative paths so it can be moved to another drive or computer.',
        )
        default = self._destination_state or self.settings.last_archive_destination or str(default_archive_parent())
        self.destination_var = tk.StringVar(value=default)
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=12)
        ttk.Entry(row, textvariable=self.destination_var).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=self._browse_destination).pack(side='left', padx=(8, 0))
        ttk.Label(
            self.body,
            text='Cleanup behavior: Archive Only — Keep Original Messages',
            font=('Segoe UI', 10, 'bold'),
        ).pack(anchor='w', pady=10)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=20)
        ttk.Button(buttons, text='Back', command=self._back_to_date_range).pack(side='left')
        ttk.Button(buttons, text='Preview Archive', command=self._preview).pack(side='right')

    def _back_to_date_range(self) -> None:
        self._destination_state = self.destination_var.get().strip()
        self.show_date_range()

    def _preview(self):
        self._destination_state = self.destination_var.get().strip()
        self.archive_parent = Path(self._destination_state).expanduser()
        self.account_metadata = self.provider.get_account_metadata()
        destination = resolve_archive_root(
            self.archive_parent, self.date_start, self.date_end, account_metadata=self.account_metadata
        )
        self.selection = ArchiveSelection(
            self._selected_folder_ids_state,
            self.date_start,
            self.date_end,
            destination,
        )
        self.status.set('Calculating archive preview…')

        def work():
            try:
                preview = self.controller.preview(self.selection)
                self.queue.put(('preview', preview))
            except Exception as exc:
                self.queue.put(('error', 'Archive preview failed', str(exc)))

        Thread(target=work, daemon=True).start()

    def show_preview(self, preview):
        self.last_preview = preview
        self._clear()
        self._title('Archive preview', 'Nothing has been changed in your mailbox.')
        start_display = format_user_date(self.date_start, empty='earliest')
        end_display = format_user_date(self.date_end, empty='latest')
        lines = [
            ('Microsoft account', format_account_identity(getattr(self, 'account_metadata', {}))),
            ('Folders', ', '.join(self._selected_folder_names_state)),
            ('Date range', f'{start_display} through {end_display} (inclusive)'),
            ('Archive folder', str(self.selection.destination)),
            ('Messages', f'{preview.message_count:,}'),
            ('Estimated archive size', format_bytes(preview.estimated_bytes)),
            ('Available disk space', format_bytes(preview.available_bytes)),
            ('Include attachments', 'Yes'),
            ('Cleanup behavior', preview.cleanup_behavior),
        ]
        for label, value in lines:
            row = ttk.Frame(self.body)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=label + ':', width=24, font=('Segoe UI', 10, 'bold')).pack(side='left', anchor='n')
            ttk.Label(row, text=value, wraplength=620).pack(side='left', anchor='w')
        if not preview.destination_writable:
            ttk.Label(self.body, text='Cannot start: ' + preview.destination_error, wraplength=800).pack(anchor='w', pady=12)
        elif preview.likely_has_space is False:
            ttk.Label(
                self.body,
                text='Warning: the selected destination may not have enough free space. Archiving will stop safely if writes fail.',
                wraplength=800,
            ).pack(anchor='w', pady=12)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=20)
        ttk.Button(buttons, text='Back', command=self.show_destination).pack(side='left')
        start = ttk.Button(buttons, text='Start Archive', command=self._start_archive)
        start.pack(side='right')
        if not preview.destination_writable:
            start.state(['disabled'])

    def _sign_out(self):
        previous_provider = self.provider
        super()._sign_out()
        if previous_provider is not None and self.provider is None and self.controller is None:
            self._reset_wizard_state()
            self.folder_rows = []
            self.status.set('Signed out')
            self.show_welcome()
