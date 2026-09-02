from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mailarchive.application.controller import ArchiveSelection, MailArchiveController
from mailarchive.archive.manager import ArchiveRegistry
from mailarchive.configuration.settings import AppSettings, SettingsStore, default_archive_parent, valid_window_geometry
from mailarchive.archive.planning import resolve_archive_root
from mailarchive.ui.date_ranges import PRESETS, resolve_date_range
from mailarchive.ui.formatting import archive_manager_label, cleanup_confirmation_text, format_account_identity, format_bytes


class MailArchiveApp(tk.Tk):
    """Normal-user wizard. Safety decisions remain in controller/domain services."""

    def __init__(self, provider_session, settings_store: SettingsStore, registry: ArchiveRegistry):
        super().__init__()
        self.title('MailArchive')
        self.provider_session = provider_session
        self.settings_store = settings_store
        self.settings = settings_store.load()
        self.minsize(820, 600)
        geometry = valid_window_geometry(self.settings.window_geometry)
        self.geometry(geometry or '940x680')
        self.registry = registry
        self.controller = None
        self.provider = None
        self.folder_rows = []
        self.selection = None
        self.current_archive = None
        self.last_archive_result = None
        self.queue = Queue()
        self._build_shell()
        self.protocol('WM_DELETE_WINDOW', self._close_app)
        self.show_welcome()
        self.after(100, self._drain_queue)

    def _close_app(self):
        try:
            self.settings.window_geometry = valid_window_geometry(self.geometry())
            self.settings_store.save(self.settings)
        finally:
            self.destroy()

    def _build_shell(self):
        style = ttk.Style(self)
        try:
            style.theme_use('vista')
        except tk.TclError:
            pass
        self.header = ttk.Frame(self, padding=(18, 14))
        self.header.pack(fill='x')
        ttk.Label(self.header, text='MailArchive', font=('Segoe UI', 20, 'bold')).pack(side='left')
        ttk.Label(self.header, text='Preserve first. Verify second. Cleanup only by choice.').pack(side='right')
        self.body = ttk.Frame(self, padding=20)
        self.body.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Ready')
        ttk.Label(self, textvariable=self.status, anchor='w', padding=(12, 6)).pack(fill='x', side='bottom')

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    def _title(self, text, subtitle=''):
        ttk.Label(self.body, text=text, font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        if subtitle:
            ttk.Label(self.body, text=subtitle, wraplength=820).pack(anchor='w', pady=(4, 18))

    def show_welcome(self):
        self._clear()
        self._title('Archive Microsoft 365 mail locally', 'Your archive stays local and remains readable without Outlook or an internet connection.')
        card = ttk.LabelFrame(self.body, text='Microsoft account', padding=18)
        card.pack(fill='x', pady=10)
        ttk.Label(card, text='MailArchive uses Microsoft’s sign-in window. Your Microsoft password is never entered into MailArchive.', wraplength=760).pack(anchor='w')
        ttk.Button(card, text='Sign in to Microsoft 365', command=self._sign_in).pack(anchor='w', pady=(14, 0))
        actions = ttk.Frame(self.body)
        actions.pack(fill='x', pady=20)
        ttk.Button(actions, text='Existing Archives', command=self.show_archive_manager).pack(side='left')
        ttk.Button(actions, text='Settings', command=self.show_settings).pack(side='left', padx=8)

    def _sign_in(self):
        self.status.set('Opening Microsoft sign-in…')
        def work():
            try:
                provider = self.provider_session.sign_in_archive()
                folders = provider.list_folders()
                self.queue.put(('signed_in', provider, folders))
            except Exception as exc:
                self.queue.put(('error', 'Microsoft sign-in failed', str(exc)))
        Thread(target=work, daemon=True).start()

    def show_folders(self):
        self._clear()
        self._title('Choose folders', 'Select one or more folders. MailArchive will not silently expand this to the entire mailbox.')
        self.folder_list = tk.Listbox(self.body, selectmode='extended', height=18, exportselection=False)
        self.folder_list.pack(fill='both', expand=True)
        for index, row in enumerate(self.folder_rows):
            self.folder_list.insert('end', row.get('name') or row['id'])
            if row['id'] in self.settings.preferred_folder_ids:
                self.folder_list.selection_set(index)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=14)
        ttk.Button(buttons, text='Back', command=self.show_welcome).pack(side='left')
        ttk.Button(buttons, text='Next: Date Range', command=self.show_date_range).pack(side='right')

    def show_date_range(self):
        selected = list(self.folder_list.curselection())
        if not selected:
            messagebox.showwarning('Select folders', 'Select at least one mailbox folder.')
            return
        self.selected_folder_ids = tuple(self.folder_rows[i]['id'] for i in selected)
        self.selected_folder_names = tuple((self.folder_rows[i].get('name') or self.folder_rows[i]['id']) for i in selected)
        self._clear()
        self._title('Choose date range', 'Boundary dates are inclusive.')
        self.preset = tk.StringVar(value='Older than 1 year')
        ttk.Label(self.body, text='Preset').pack(anchor='w')
        combo = ttk.Combobox(self.body, values=PRESETS, textvariable=self.preset, state='readonly', width=32)
        combo.pack(anchor='w', pady=(4, 14))
        grid = ttk.Frame(self.body)
        grid.pack(anchor='w')
        ttk.Label(grid, text='Custom start (YYYY-MM-DD)').grid(row=0, column=0, sticky='w')
        ttk.Label(grid, text='Custom end (YYYY-MM-DD)').grid(row=0, column=1, sticky='w', padx=(18, 0))
        self.start_entry = ttk.Entry(grid, width=24)
        self.end_entry = ttk.Entry(grid, width=24)
        self.start_entry.grid(row=1, column=0, pady=4)
        self.end_entry.grid(row=1, column=1, padx=(18, 0), pady=4)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=20)
        ttk.Button(buttons, text='Back', command=self.show_folders).pack(side='left')
        ttk.Button(buttons, text='Next: Destination', command=self.show_destination).pack(side='right')

    def show_destination(self):
        try:
            self.date_start, self.date_end = resolve_date_range(
                self.preset.get(), custom_start=self.start_entry.get(), custom_end=self.end_entry.get()
            )
        except ValueError as exc:
            messagebox.showerror('Date range', str(exc))
            return
        self._clear()
        self._title('Choose archive parent folder', 'MailArchive creates a date-range archive folder here. The archive uses relative paths so it can be moved to another drive or computer.')
        default = self.settings.last_archive_destination or str(default_archive_parent())
        self.destination_var = tk.StringVar(value=default)
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=12)
        ttk.Entry(row, textvariable=self.destination_var).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=self._browse_destination).pack(side='left', padx=(8, 0))
        ttk.Label(self.body, text='Cleanup behavior: Archive Only — Keep Original Messages', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=10)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=20)
        ttk.Button(buttons, text='Back', command=self.show_date_range).pack(side='left')
        ttk.Button(buttons, text='Preview Archive', command=self._preview).pack(side='right')

    def _browse_destination(self):
        path = filedialog.askdirectory(title='Choose MailArchive destination')
        if path:
            self.destination_var.set(path)

    def _preview(self):
        self.archive_parent = Path(self.destination_var.get()).expanduser()
        self.account_metadata = self.provider.get_account_metadata()
        destination = resolve_archive_root(
            self.archive_parent, self.date_start, self.date_end, account_metadata=self.account_metadata
        )
        self.selection = ArchiveSelection(self.selected_folder_ids, self.date_start, self.date_end, destination)
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
        lines = [
            ('Microsoft account', format_account_identity(getattr(self, 'account_metadata', {}))),
            ('Folders', ', '.join(self.selected_folder_names)),
            ('Date range', f'{self.date_start or "earliest"} through {self.date_end or "latest"} (inclusive)'),
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
            ttk.Label(self.body, text='Warning: the selected destination may not have enough free space. Archiving will stop safely if writes fail.', wraplength=800).pack(anchor='w', pady=12)
        buttons = ttk.Frame(self.body)
        buttons.pack(fill='x', pady=20)
        ttk.Button(buttons, text='Back', command=self.show_destination).pack(side='left')
        start = ttk.Button(buttons, text='Start Archive', command=self._start_archive)
        start.pack(side='right')
        if not preview.destination_writable:
            start.state(['disabled'])

    def _start_archive(self):
        # Persist the user-selected parent, not the generated date-range child.
        self.settings.last_archive_destination = str(self.archive_parent)
        self.settings.preferred_folder_ids = list(self.selection.folder_ids)
        self.settings_store.save(self.settings)
        self._clear()
        self._title('Archiving mail', 'You can cancel safely. Verified work is preserved and the online mailbox remains untouched.')
        self.progress_text = tk.StringVar(value='Starting…')
        self.count_text = tk.StringVar(value='Discovered 0   Downloaded 0   Verified 0   Skipped 0   Failed 0   Written 0 B')
        ttk.Label(self.body, textvariable=self.progress_text, font=('Segoe UI', 12)).pack(anchor='w', pady=10)
        ttk.Label(self.body, textvariable=self.count_text, wraplength=820).pack(anchor='w')
        self._progress_total = max(0, int(getattr(getattr(self, 'last_preview', None), 'message_count', 0) or 0))
        self.progressbar = ttk.Progressbar(self.body, mode='determinate', maximum=max(1, self._progress_total), value=0)
        self.progressbar.pack(fill='x', pady=16)
        self._counts = {'discovered': 0, 'downloaded': 0, 'verified': 0, 'skipped': 0, 'failed': 0, 'bytes_written': 0}
        self._current_folder = ''
        ttk.Button(self.body, text='Cancel Safely', command=self._cancel_archive).pack(anchor='w')

        def progress(event):
            self.queue.put(('progress', event))

        def work():
            try:
                result = self.controller.run_archive(self.selection, progress=progress)
                self.queue.put(('archive_done', result))
            except Exception as exc:
                self.queue.put(('error', 'Archival interrupted', str(exc)))
        Thread(target=work, daemon=True).start()

    def _refresh_progress_summary(self):
        counts = self._counts
        completed = counts['verified'] + counts['skipped'] + counts['failed']
        total = max(self._progress_total, counts['discovered'], completed)
        if total > 0:
            self.progressbar.configure(maximum=total)
            self.progressbar['value'] = min(completed, total)
            percent = int((completed * 100) / total)
        else:
            percent = 0
        folder = f"   Folder {self._current_folder}" if self._current_folder else ''
        self.count_text.set(
            f"Overall {percent}%{folder}\n"
            f"Discovered {counts['discovered']:,}   Downloaded {counts['downloaded']:,}   "
            f"Verified {counts['verified']:,}   Skipped {counts['skipped']:,}   Failed {counts['failed']:,}   "
            f"Written {format_bytes(counts['bytes_written'])}"
        )

    def _cancel_archive(self):
        self.controller.cancel_archive()
        self.status.set('Cancellation requested; finishing the current safe boundary…')

    def show_completion(self, result):
        self.current_archive = result.archive_root
        self.last_archive_result = result
        self._clear()
        title = 'Archive complete' if result.completed else 'Archive stopped with incomplete items'
        self._title(title)
        stop_line = f'\nStop reason: {result.stop_reason}' if result.stop_reason else ''
        ttk.Label(
            self.body,
            text=(
                f'Job status: {result.status}\n'
                f'Messages found: {result.discovered:,}\n'
                f'Messages processed: {result.processed:,}\n'
                f'Messages archived/verified: {result.verified:,}\n'
                f'Messages skipped (already verified): {result.skipped:,}\n'
                f'Failures: {result.failed:,}\n'
                f'Archive size: {format_bytes(result.archive_size_bytes)}\n'
                f'Cancelled: {"Yes" if result.cancelled else "No"}'
                f'{stop_line}\nArchive: {result.archive_root}'
            ),
            justify='left',
        ).pack(anchor='w', pady=10)
        actions = ttk.Frame(self.body)
        actions.pack(fill='x', pady=18)
        ttk.Button(actions, text='Open Archive', command=lambda: self.controller.open_archive(result.archive_root)).pack(side='left')
        ttk.Button(actions, text='Open Folder', command=lambda: self._open_folder(result.archive_root)).pack(side='left', padx=6)
        ttk.Button(actions, text='View Report', command=lambda: self._open_report(result.archive_root)).pack(side='left')
        if not result.completed:
            ttk.Label(
                self.body,
                text='Mailbox cleanup is not offered from an incomplete archive run. Resume the archive first; already verified messages will be skipped and all online messages remain untouched.',
                wraplength=760,
            ).pack(anchor='w', pady=12)
            incomplete_actions = ttk.Frame(self.body)
            incomplete_actions.pack(fill='x', pady=(4, 0))
            if result.resumable and self.selection is not None:
                ttk.Button(incomplete_actions, text='Resume Archive', command=self._resume_archive).pack(side='left')
            ttk.Button(incomplete_actions, text='Back To MailArchive', command=self.show_welcome).pack(side='left', padx=(8, 0))
            return
        cleanup = ttk.LabelFrame(self.body, text='Optional mailbox cleanup', padding=14)
        cleanup.pack(fill='x', pady=12)
        ttk.Label(cleanup, text='Archive Only is complete. You may keep all original messages online, or explicitly move only still-verified messages to Deleted Items.', wraplength=760).pack(anchor='w')
        ttk.Button(cleanup, text='Keep Mail In Outlook', command=self.show_welcome).pack(side='left', pady=(12, 0))
        ttk.Button(cleanup, text='Move Verified Mail To Deleted Items', command=self._confirm_cleanup).pack(side='left', padx=8, pady=(12, 0))


    def _resume_archive(self):
        result = self.last_archive_result
        if result is None or not result.resumable or self.selection is None:
            messagebox.showwarning('Resume unavailable', 'There is no resumable archive job in this session.')
            return
        self._clear()
        self._title('Resuming archive', 'Already verified messages are preserved and skipped. Mailbox cleanup remains disabled until the job completes.')
        self.progress_text = tk.StringVar(value='Resuming…')
        self.count_text = tk.StringVar(value='Discovered 0   Downloaded 0   Verified 0   Skipped 0   Failed 0   Written 0 B')
        ttk.Label(self.body, textvariable=self.progress_text, font=('Segoe UI', 12)).pack(anchor='w', pady=10)
        ttk.Label(self.body, textvariable=self.count_text, wraplength=820).pack(anchor='w')
        self._progress_total = max(0, int(result.discovered or 0))
        self.progressbar = ttk.Progressbar(self.body, mode='determinate', maximum=max(1, self._progress_total), value=0)
        self.progressbar.pack(fill='x', pady=16)
        self._counts = {'discovered': 0, 'downloaded': 0, 'verified': 0, 'skipped': 0, 'failed': 0, 'bytes_written': 0}
        self._current_folder = ''
        ttk.Button(self.body, text='Cancel Safely', command=self._cancel_archive).pack(anchor='w')

        def progress(event):
            self.queue.put(('progress', event))

        def work():
            try:
                resumed = self.controller.run_archive(self.selection, progress=progress, job_id=result.job_id)
                self.queue.put(('archive_done', resumed))
            except Exception as exc:
                self.queue.put(('error', 'Archive resume interrupted', str(exc)))
        Thread(target=work, daemon=True).start()

    def _confirm_cleanup(self):
        try:
            plan = self.controller.cleanup_plan(self.current_archive)
        except Exception as exc:
            messagebox.showerror('Cleanup unavailable', str(exc))
            return
        if not plan.cleanup_allowed:
            messagebox.showwarning(
                'Cleanup safety block',
                'Mailbox cleanup is disabled until the interrupted storage operation is successfully resumed.\n\n'
                + (plan.blocked_reason or 'Archive storage verification is incomplete.'),
            )
            return
        if not plan.archive_ids:
            messagebox.showinfo('No eligible messages', 'No messages currently pass all cleanup eligibility checks.')
            return
        if not messagebox.askyesno('Move verified mail to Deleted Items', cleanup_confirmation_text(plan), icon='warning'):
            return
        self.status.set('Requesting Microsoft permission for cleanup…')
        def work():
            try:
                cleanup_provider = self.provider_session.cleanup_provider()
                metadata = {
                    'date_range': {'start': plan.date_start, 'end': plan.date_end, 'inclusive': True},
                    'folders': list(plan.folders),
                    'eligible_count': plan.verified_eligible_count,
                }
                results = self.controller.execute_cleanup(
                    self.current_archive, plan.archive_ids, cleanup_provider=cleanup_provider, metadata=metadata
                )
                self.queue.put(('cleanup_done', results))
            except Exception as exc:
                self.queue.put(('error', 'Cleanup failed safely', str(exc)))
        Thread(target=work, daemon=True).start()

    def show_archive_manager(self):
        self._clear()
        self._title('Existing archives', 'Removing an archive from this list never deletes its files.')
        archives = self.registry.list_archives()
        self.archive_list = tk.Listbox(self.body, height=16, exportselection=False)
        self.archive_list.pack(fill='both', expand=True)
        self._archive_rows = archives
        for item in archives:
            self.archive_list.insert('end', archive_manager_label(item))
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=12)
        ttk.Button(row, text='Open', command=self._manager_open).pack(side='left')
        ttk.Button(row, text='Open Folder', command=self._manager_open_folder).pack(side='left', padx=6)
        ttk.Button(row, text='Verify', command=self._manager_verify).pack(side='left', padx=(0, 6))
        ttk.Button(row, text='Remove From List', command=self._manager_remove).pack(side='left')
        ttk.Button(row, text='Back', command=self.show_welcome).pack(side='right')

    def _selected_archive(self):
        chosen = self.archive_list.curselection()
        return self._archive_rows[chosen[0]] if chosen else None

    def _manager_open(self):
        row = self._selected_archive()
        if row and row.get('exists'):
            self.controller.open_archive(row['path']) if self.controller else self._open_standalone_archive(row['path'])

    def _open_standalone_archive(self, path):
        from mailarchive.viewer.launcher import launch_archive
        self.registry.register(path, opened=True)
        launch_archive(path)

    def _manager_open_folder(self):
        row = self._selected_archive()
        if row and row.get('exists'):
            self._open_folder(row['path'])

    def _manager_verify(self):
        row = self._selected_archive()
        if not row or not row.get('exists'):
            return
        try:
            result = self.controller.verify_archive(row['path']) if self.controller else __import__('mailarchive.integrity.verify_archive', fromlist=['ArchiveIntegrityVerifier']).ArchiveIntegrityVerifier(row['path']).verify()
            messagebox.showinfo('Archive verification', f"Status: {result['status']}\nIssues: {len(result['issues'])}")
        except Exception as exc:
            messagebox.showerror('Archive verification', str(exc))

    def _manager_remove(self):
        row = self._selected_archive()
        if row:
            self.registry.remove_from_list(row['path'])
            self.show_archive_manager()

    def show_settings(self):
        self._clear()
        self._title('Settings')
        ttk.Label(self.body, text='Authentication tokens are stored separately using Windows protection and are not stored in this settings file.', wraplength=800).pack(anchor='w', pady=8)
        ttk.Button(self.body, text='Sign out / forget Microsoft account', command=self._sign_out).pack(anchor='w', pady=8)
        ttk.Button(self.body, text='Reset non-secret settings', command=self._reset_settings).pack(anchor='w')
        ttk.Button(self.body, text='Back', command=self.show_welcome).pack(anchor='w', pady=20)

    def _sign_out(self):
        try:
            self.provider_session.sign_out()
            self.provider = None
            self.controller = None
            messagebox.showinfo('Signed out', 'Cached Microsoft authentication state was removed.')
        except Exception as exc:
            messagebox.showerror('Sign out', str(exc))

    def _reset_settings(self):
        self.settings = AppSettings()
        self.settings_store.save(self.settings)
        messagebox.showinfo('Settings reset', 'Non-secret MailArchive settings were reset.')

    def _open_folder(self, path):
        try:
            os.startfile(str(path))
        except Exception as exc:
            messagebox.showerror('Open folder', str(exc))

    def _open_report(self, root):
        report = Path(root) / 'reports' / 'archive_report.json'
        if not report.exists():
            report = Path(root) / 'archive_info.json'
        if not report.exists():
            report = Path(root) / 'manifest.json'
        try:
            os.startfile(str(report))
        except Exception as exc:
            messagebox.showerror('Open report', str(exc))

    def _drain_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == 'signed_in':
                    self.provider, self.folder_rows = item[1], item[2]
                    self.controller = MailArchiveController(self.provider, registry=self.registry)
                    self.status.set('Signed in')
                    self.show_folders()
                elif kind == 'preview':
                    self.status.set('Preview ready')
                    self.show_preview(item[1])
                elif kind == 'progress':
                    event = item[1]
                    name = event['event']
                    if name == 'discovered':
                        self._counts['discovered'] = event['discovered']
                        self._current_folder = str(event.get('folder') or '')
                        self.progress_text.set(f"Discovering {self._current_folder}")
                    elif name == 'downloading':
                        self.progress_text.set('Downloading original MIME…')
                    elif name == 'downloaded':
                        self._counts['downloaded'] += 1
                        self.progress_text.set('Original MIME downloaded; preserving locally…')
                    elif name == 'written':
                        self._counts['bytes_written'] += int(event.get('bytes_written') or 0)
                        self.progress_text.set('Original MIME written; verifying SHA-256 and archive records…')
                    elif name == 'skipped':
                        self._counts['skipped'] += 1
                        self.progress_text.set('Already verified locally; skipped safely')
                    elif name == 'verified':
                        self._counts['verified'] += 1
                        self.progress_text.set('Verified locally')
                    elif name == 'failed':
                        self._counts['failed'] += 1
                        self.progress_text.set('One message failed; continuing safely')
                    elif name == 'stopped':
                        self.progress_text.set(f"Archive stopped safely: {event.get('reason', 'interrupted')}")
                    elif name == 'completed':
                        self.progress_text.set('Finalizing archive metadata…')
                    self._refresh_progress_summary()
                elif kind == 'archive_done':
                    self.progressbar.stop()
                    self.status.set('Archive job finished')
                    self.show_completion(item[1])
                elif kind == 'cleanup_done':
                    moved = sum(status == 'MOVED' for _, status in item[1])
                    unknown = sum(status == 'UNKNOWN_MOVE_OUTCOME' for _, status in item[1])
                    not_moved = len(item[1]) - moved - unknown
                    self.status.set('Cleanup attempt finished')
                    detail = (
                        f'Moved to Deleted Items: {moved}\n'
                        f'Not moved: {not_moved}\n'
                        f'Outcome uncertain: {unknown}\n'
                        'No permanent deletion was performed.'
                    )
                    if unknown:
                        detail += (
                            '\n\nAn uncertain item may already be in Deleted Items. MailArchive will not retry it automatically; '
                            'check the mailbox and cleanup report before doing anything else.'
                        )
                    messagebox.showinfo('Cleanup report', detail)
                elif kind == 'error':
                    self.status.set(item[1])
                    messagebox.showerror(item[1], item[2])
        except Empty:
            pass
        finally:
            self.after(100, self._drain_queue)
