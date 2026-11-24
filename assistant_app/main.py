"""Native desktop GUI, explicitly approved computer actions."""
from __future__ import annotations
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, simpledialog
from datetime import datetime
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from assistant_app import core, workspace, diagnostics, voice, agent, server, proposals, maintenance, tasks, downloads, recognition, conversations, streaming, review_queue, project_context, project_audit, project_snapshots, workflows, windows_tools, model_inventory, runtime_setup, data_portability
else:
    from . import core, workspace, diagnostics, voice, agent, server, proposals, maintenance, tasks, downloads, recognition, conversations, streaming, review_queue, project_context, project_audit, project_snapshots, workflows, windows_tools, model_inventory, runtime_setup, data_portability

BG = '#151a21'
PANEL = '#222936'
FG = '#e8edf3'
ACCENT = '#58c6ba'

class App:
    def __init__(self, root):
        self.root = root
        self.root.title('PersonalAI — 4.2.0')
        self.root.geometry('1080x760')
        self.root.minsize(850, 600)
        self.root.configure(bg=BG)
        self.settings = core.load_config()
        self.api_key = os.environ.get('PERSONALAI_API_KEY', '')
        self.events = queue.Queue()
        self.server = server.ServerManager()
        self.busy = False
        self.last_answer = ''
        self.pending_plan = False
        self.stop_generation = threading.Event()
        self.stream_open = False
        self.conversation_rows = conversations.list_all()
        self.current_conversation = self.conversation_rows[0][0]
        self.setup_ui()
        self.refresh_conversations(select_id=self.current_conversation)
        self.reload_conversation()
        self.root.after(120, self.poll)
        self.root.protocol('WM_DELETE_WINDOW', self.close_app)

    def button(self, parent, title, command):
        return tk.Button(parent, text=title, command=command, bg=PANEL, fg=FG,
                         activebackground=ACCENT, activeforeground=BG, borderwidth=0, padx=13, pady=9)

    def setup_ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill='x', padx=18, pady=12)
        tk.Label(header, text='◈ PersonalAI', bg=BG, fg=ACCENT, font=('Segoe UI', 20, 'bold')).pack(side='left')
        self.status = tk.Label(header, text='Готов к работе', bg=BG, fg=FG)
        self.status.pack(side='right')
        dialogue = tk.Frame(self.root, bg=BG)
        dialogue.pack(fill='x', padx=18, pady=(0, 10))
        tk.Label(dialogue, text='Диалог:', bg=BG, fg=FG).pack(side='left', padx=(0, 8))
        self.dialogue_combo = ttk.Combobox(dialogue, state='readonly', width=40)
        self.dialogue_combo.pack(side='left', padx=(0, 8))
        self.dialogue_combo.bind('<<ComboboxSelected>>', self.switch_conversation)
        for label, command in [('Новый', self.new_conversation), ('Переименовать', self.rename_conversation),
                               ('Удалить', self.delete_conversation), ('Поиск', self.search_dialogues)]:
            self.button(dialogue, label, command).pack(side='left', padx=(0, 6))
        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill='x', padx=18, pady=(0, 10))
        for title, action in [('Настройки', self.show_settings), ('Информация о ПК', self.inspect_pc),
                              ('Открыть файл', self.open_file), ('Очистить историю', self.clear),
                              ('Папка данных', self.open_data_folder)]:
            self.button(actions, title, action).pack(side='left', padx=(0, 8))
        grouped_actions = [
            [('Рабочая папка', self.choose_workspace), ('Файлы', self.browse_workspace),
             ('Анализ файла', self.analyze_file), ('Редактор', self.edit_workspace_file),
             ('План изменений ИИ', self.plan_changes), ('Очередь проверки', self.review_queue_window), ('Контекст проекта', self.project_context_window), ('Аудит проекта', self.audit_project_window), ('Снимки проекта', self.project_snapshots_window), ('Сценарии', self.workflows_window), ('Программы Windows', self.windows_apps_window)],
            [('Заметки', self.notes), ('Резервные копии', self.manage_backups),
             ('Хранилище', self.show_storage), ('Архив данных', self.backup_data_window), ('Задачи', self.manage_tasks), ('Журнал', self.show_audit),
             ('Экспорт', self.export_chat)],
            [('Проверить ИИ', self.check_model), ('Сервер ИИ', self.manage_server), ('Загрузить GGUF', self.model_download), ('Мои модели', self.models_window), ('Мастер локального ИИ', self.runtime_setup_window),
             ('Озвучить ответ', self.speak_answer), ('Диктовка', self.dictation)]
        ]
        for group in grouped_actions:
            # Split long toolbars so controls remain visible on 850px-wide windows.
            for start in range(0, len(group), 3):
                toolbar = tk.Frame(self.root, bg=BG)
                toolbar.pack(fill='x', padx=18, pady=(0, 5))
                for title, action in group[start:start + 3]:
                    self.button(toolbar, title, action).pack(side='left', padx=(0, 7))
        self.chat_area = scrolledtext.ScrolledText(self.root, wrap='word', font=('Segoe UI', 11),
                                bg=PANEL, fg=FG, insertbackground=FG, borderwidth=0, padx=16, pady=14,
                                state='disabled')
        self.chat_area.pack(expand=True, fill='both', padx=18, pady=(0, 10))
        self.chat_area.tag_config('name', foreground=ACCENT, font=('Segoe UI', 11, 'bold'))
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill='x', padx=18, pady=(0, 18))
        self.entry = tk.Text(bottom, height=3, font=('Segoe UI', 11), bg=PANEL, fg=FG,
                             insertbackground=FG, relief='flat', wrap='word')
        self.entry.pack(side='left', fill='both', expand=True)
        self.entry.bind('<Control-Return>', lambda event: self.send())
        self.send_button = self.button(bottom, 'Отправить\nCtrl+Enter', self.send)
        self.send_button.pack(side='right', padx=(10, 0), fill='y')
        self.button(bottom, 'Остановить', self.stop_answer).pack(side='right', padx=(10, 0), fill='y')
        self.print_chat('Система', 'PersonalAI 4.2 — чат, заметки, рабочая папка и подтверждение изменений. Для анализа файлов выберите рабочую папку. Облачный fallback по умолчанию отключён.')

    def refresh_conversations(self, select_id=None):
        self.conversation_rows = conversations.list_all()
        self.dialogue_combo['values'] = [f'#{cid} — {title}' for cid, title in self.conversation_rows]
        ids = [cid for cid, _ in self.conversation_rows]
        if select_id not in ids:
            select_id = ids[0]
        self.current_conversation = select_id
        self.dialogue_combo.current(ids.index(select_id))

    def reload_conversation(self):
        self.chat_area.configure(state='normal')
        self.chat_area.delete('1.0', 'end')
        self.chat_area.configure(state='disabled')
        for role, message in conversations.history(self.current_conversation, 100):
            self.print_chat('Вы' if role == 'user' else 'ИИ', message)

    def switch_conversation(self, _event=None):
        if self.busy:
            self.refresh_conversations(self.current_conversation)
            messagebox.showinfo('Диалоги', 'Дождитесь окончания текущего ответа.', parent=self.root)
            return
        selected = self.dialogue_combo.current()
        if selected >= 0:
            self.current_conversation = self.conversation_rows[selected][0]
            self.reload_conversation()

    def new_conversation(self):
        if self.busy:
            return
        new_id = conversations.create()
        self.refresh_conversations(new_id)
        self.reload_conversation()

    def rename_conversation(self):
        title = simpledialog.askstring('Диалог', 'Новое название:', parent=self.root)
        if title is not None:
            try:
                conversations.rename(self.current_conversation, title)
                self.refresh_conversations(self.current_conversation)
            except ValueError as exc:
                messagebox.showerror('Ошибка', str(exc), parent=self.root)

    def delete_conversation(self):
        if self.busy:
            return
        if not self.approve('Удалить текущий диалог и все его сообщения?'):
            return
        try:
            conversations.delete(self.current_conversation)
            self.refresh_conversations()
            self.reload_conversation()
        except ValueError as exc:
            messagebox.showerror('Ошибка', str(exc), parent=self.root)

    def print_chat(self, name, content):
        self.chat_area.configure(state='normal')
        self.chat_area.insert('end', name + ':\n', 'name')
        self.chat_area.insert('end', content + '\n\n')
        self.chat_area.configure(state='disabled')
        self.chat_area.see('end')

    def set_busy(self, value, label='Готов к работе'):
        self.busy = value
        self.status.configure(text=label)
        self.send_button.configure(state='disabled' if value else 'normal')

    def stop_answer(self):
        if self.busy:
            self.stop_generation.set()
            self.status.configure(text='Остановка запроса…')

    def append_stream(self, chunk):
        self.chat_area.configure(state='normal')
        if not self.stream_open:
            self.chat_area.insert('end', 'ИИ (поток):\n', 'name')
            self.stream_open = True
        self.chat_area.insert('end', chunk)
        self.chat_area.configure(state='disabled')
        self.chat_area.see('end')

    def close_stream(self):
        if self.stream_open:
            self.chat_area.configure(state='normal')
            self.chat_area.insert('end', '\n\n')
            self.chat_area.configure(state='disabled')
            self.stream_open = False

    def send(self):
        message = self.entry.get('1.0', 'end').strip()
        if self.busy or not message:
            return
        self.entry.delete('1.0', 'end')
        conversations.add_message(self.current_conversation, 'user', message)
        self.print_chat('Вы', message)
        messages = [{'role': 'system', 'content': core.SYSTEM_PROMPT}]
        messages.extend({'role': role, 'content': content} for role, content in conversations.history(self.current_conversation, max(2, min(int(self.settings.get('max_context',18)), 50))))
        self.set_busy(True, 'ИИ обрабатывает запрос...')
        self.stop_generation.clear()
        cfg, key = self.settings.copy(), self.api_key
        def worker():
            try:
                if cfg.get('streaming_enabled', False):
                    result, provider = streaming.chat_stream(cfg, messages, key,
                        lambda part: self.events.put(('token', part)), self.stop_generation)
                    self.events.put(('stream_answer', result, provider))
                else:
                    result, provider = core.chat(cfg, messages, key)
                    if self.stop_generation.is_set():
                        self.events.put(('cancelled',))
                    else:
                        self.events.put(('answer', result, provider))
            except streaming.Cancelled:
                self.events.put(('cancelled',))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'token':
                    self.append_stream(event[1])
                elif event[0] == 'stream_answer':
                    _, answer, provider = event
                    self.close_stream()
                    conversations.add_message(self.current_conversation, 'assistant', answer, provider)
                    self.last_answer = answer
                    self.set_busy(False, 'Готов к работе')
                    if self.settings.get('voice_output'):
                        self.speak_answer()
                elif event[0] == 'cancelled':
                    self.close_stream()
                    self.print_chat('Система', 'Генерация остановлена; неполный ответ не сохранён.')
                    self.set_busy(False, 'Остановлено')
                elif event[0] == 'answer':
                    _, answer, provider = event
                    conversations.add_message(self.current_conversation, 'assistant', answer, provider)
                    self.last_answer = answer
                    self.print_chat('ИИ (' + provider + ')', answer)
                    self.set_busy(False)
                    if self.settings.get('voice_output'):
                        self.speak_answer()
                elif event[0] == 'project_answer':
                    self.set_busy(False)
                    self.last_answer = event[1]
                    self.print_chat('ИИ — анализ проекта (' + event[2] + ')', event[1])
                    conversations.add_message(self.current_conversation, 'assistant', '[Анализ выбранных файлов]\n' + event[1], event[2])
                elif event[0] == 'project_audit':
                    self.set_busy(False)
                    self.text_window('Локальный аудит проекта — отчёт', event[1])
                elif event[0] == 'plan':
                    self.set_busy(False)
                    self.review_plan(event[1], event[2])
                elif event[0] == 'error':
                    self.close_stream()
                    self.print_chat('Ошибка', event[1])
                    self.set_busy(False, 'Ошибка подключения')
                elif event[0] == 'dictation':
                    self.set_busy(False, 'Распознавание завершено')
                    if event[1]:
                        self.entry.insert('insert', event[1] + ' ')
                    else:
                        messagebox.showinfo('Диктовка', 'Речь не распознана', parent=self.root)
                elif event[0] == 'download_progress':
                    self.status.configure(text=f'Загрузка модели: {event[1] / 1024**2:.0f} МБ')
                elif event[0] == 'download_complete':
                    self.set_busy(False, 'Загрузка завершена')
                    self.print_chat('Система', 'Модель загружена и проверена по SHA-256: ' + event[1])
                elif event[0] == 'speak_done':
                    self.status.configure(text=event[1])
                elif event[0] == 'info':
                    self.print_chat('Система', event[1])
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(120, self.poll)

    def approve(self, what):
        allowed = messagebox.askyesno('Подтверждение действия',
                    'Помощник предлагает действие:\n\n' + what + '\n\nРазрешить выполнение?', parent=self.root)
        core.audit(what, 'approved' if allowed else 'denied')
        return allowed

    def inspect_pc(self):
        if self.busy or not self.approve('Считать основные характеристики Windows (без изменений)'):
            return
        self.set_busy(True, 'Считывание параметров ПК...')
        def worker():
            try:
                self.events.put(('info', core.system_info()))
                core.audit('Системная информация', 'done')
            except Exception as exc:
                self.events.put(('info', 'Не удалось получить сведения: ' + str(exc)))
                core.audit('Системная информация', 'failed', str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def open_file(self):
        file = filedialog.askopenfilename(parent=self.root)
        if not file:
            return
        if self.approve('Открыть выбранный файл в программе по умолчанию?\n' + file):
            try:
                os.startfile(file)
                core.audit('open_file', 'done', file)
            except Exception as exc:
                core.audit('open_file', 'failed', str(exc))
                messagebox.showerror('Ошибка', str(exc), parent=self.root)

    def open_data_folder(self):
        p = core.ensure_dir()
        if self.approve('Открыть папку данных приложения?\n' + str(p)):
            os.startfile(p)

    def clear(self):
        if self.approve('Безвозвратно очистить историю диалогов? (Журнал действий сохраняется)'):
            conversations.clear(self.current_conversation)
            self.reload_conversation()
            self.print_chat('Система', 'История удалена.')

    def show_settings(self):
        window = tk.Toplevel(self.root)
        window.title('Настройки подключения')
        window.geometry('780x680')
        window.configure(bg=BG)
        window.transient(self.root)
        window.grab_set()
        variables = {}
        fields = [('mode', 'Режим: local / hybrid / cloud'),
                  ('local_url', 'Локальный API (llama-server)'),
                  ('local_model', 'Имя локальной модели'),
                  ('cloud_url', 'Облачный API (HTTPS)'),
                  ('cloud_model', 'Модель облачного провайдера'), ('vosk_model_dir', 'Папка локальной Vosk-модели')]
        for index, (key, label) in enumerate(fields):
            tk.Label(window, text=label, bg=BG, fg=FG).grid(row=index, column=0, sticky='w', padx=15, pady=10)
            var = tk.StringVar(value=self.settings.get(key, ''))
            variables[key] = var
            ttk.Entry(window, textvariable=var, width=42).grid(row=index, column=1, sticky='ew', padx=15)
        tk.Label(window, text='API-ключ (только в памяти текущего запуска)', bg=BG, fg=FG).grid(row=6, column=0, sticky='w', padx=15, pady=10)
        key_var = tk.StringVar(value=self.api_key)
        ttk.Entry(window, textvariable=key_var, show='•', width=42).grid(row=6, column=1, sticky='ew', padx=15)
        fallback = tk.BooleanVar(value=bool(self.settings.get('cloud_fallback', False)))
        ttk.Checkbutton(window, text='Разрешить отправку контекста в облако при сбое локального ИИ', variable=fallback).grid(row=7, column=0, columnspan=2, sticky='w', padx=15)
        stream_var = tk.BooleanVar(value=bool(self.settings.get('streaming_enabled', False)))
        ttk.Checkbutton(window, text='Показывать ответ по частям (SSE; требует поддержки провайдера)', variable=stream_var).grid(row=9, column=0, columnspan=2, sticky='w', padx=15)
        voice_var = tk.BooleanVar(value=bool(self.settings.get('voice_output', False)))
        ttk.Checkbutton(window, text='Автоматически озвучивать ответы (Windows SAPI)', variable=voice_var).grid(row=8, column=0, columnspan=2, sticky='w', padx=15)
        tk.Label(window, text='Для постоянного ключа используйте PERSONALAI_API_KEY в окружении Windows.',
                 bg=BG, fg=ACCENT, wraplength=600).grid(row=10, column=0, columnspan=2, pady=10)
        def save():
            candidate = {k: v.get().strip() for k, v in variables.items()}
            if candidate['mode'] not in ('local', 'hybrid', 'cloud'):
                messagebox.showerror('Ошибка', 'Режим: local, hybrid или cloud', parent=window)
                return
            if not candidate['local_url'].startswith(('http://127.0.0.1:', 'http://localhost:')):
                messagebox.showerror('Ошибка', 'Локальный сервер должен быть на 127.0.0.1 / localhost', parent=window)
                return
            if not candidate['cloud_url'].startswith('https://'):
                messagebox.showerror('Ошибка', 'Облачный API должен использовать HTTPS', parent=window)
                return
            self.settings.update(candidate)
            self.settings['cloud_fallback'] = fallback.get()
            self.settings['voice_output'] = voice_var.get()
            self.settings['streaming_enabled'] = stream_var.get()
            self.api_key = key_var.get().strip()
            core.save_config(self.settings)
            window.destroy()
            self.status.configure(text='Настройки сохранены')
        self.button(window, 'Сохранить', save).grid(row=11, column=1, sticky='e', padx=15, pady=12)
        window.columnconfigure(1, weight=1)


    def close_app(self):
        if self.server.is_running():
            if not messagebox.askyesno('Закрытие', 'Локальный сервер ИИ запущен. Остановить его и закрыть приложение?', parent=self.root):
                return
            try:
                self.server.stop()
                core.audit('llama_server', 'stopped', 'app exit')
            except Exception as exc:
                messagebox.showerror('Ошибка остановки', str(exc), parent=self.root)
                return
        self.root.destroy()

    def manage_server(self):
        win = tk.Toplevel(self.root)
        win.title('Локальный сервер — llama.cpp')
        win.geometry('790x400')
        win.configure(bg=BG)
        entries = {}
        fields = [('server_exe', 'llama-server.exe (путь)'),
                  ('model_file', 'Модель GGUF (путь)'),
                  ('gpu_layers', 'Слои GPU (0 = CPU)'),
                  ('context', 'Контекст (токены)'),
                  ('port', 'Локальный порт')]
        defaults = {'server_exe':'', 'model_file':'', 'gpu_layers':'0', 'context':'4096', 'port':'8080'}
        for i, (key, label) in enumerate(fields):
            tk.Label(win, text=label, bg=BG, fg=FG).grid(row=i, column=0, sticky='w', padx=15, pady=10)
            var = tk.StringVar(value=str(self.settings.get(key, defaults[key])))
            entries[key] = var
            ttk.Entry(win, textvariable=var, width=70).grid(row=i, column=1, sticky='ew', padx=15)
        status = tk.Label(win, text='Запущен' if self.server.is_running() else 'Остановлен', bg=BG, fg=ACCENT)
        status.grid(row=5, column=0, columnspan=2, sticky='w', padx=15)
        buttons = tk.Frame(win, bg=BG)
        buttons.grid(row=6, column=0, columnspan=2, sticky='w', padx=15, pady=15)
        def select_exe():
            f = filedialog.askopenfilename(parent=win, filetypes=[('EXE', '*.exe')])
            if f: entries['server_exe'].set(f)
        def select_model():
            f = filedialog.askopenfilename(parent=win, filetypes=[('GGUF', '*.gguf')])
            if f: entries['model_file'].set(f)
        def start():
            values = {k: v.get().strip() for k,v in entries.items()}
            if not messagebox.askyesno('Подтверждение', 'Запустить выбранный исполняемый файл?\n' + values['server_exe'] + '\nМодель: ' + values['model_file'] + '\nGPU слои: ' + values['gpu_layers'], parent=win):
                core.audit('llama_server', 'denied', values['server_exe'])
                return
            try:
                pid = self.server.start(values['server_exe'], values['model_file'], values['gpu_layers'], values['context'], values['port'])
                self.settings.update(values)
                self.settings['local_url'] = f"http://127.0.0.1:{int(values['port'])}/v1"
                core.save_config(self.settings)
                core.audit('llama_server', 'started', 'pid ' + str(pid))
                status.configure(text='Запущен, PID ' + str(pid) + '. Инициализация модели может занять время.')
            except Exception as exc:
                core.audit('llama_server', 'failed', str(exc))
                messagebox.showerror('Не удалось запустить', str(exc), parent=win)
        def stop():
            if messagebox.askyesno('Остановка', 'Остановить сервер, который запустил PersonalAI?', parent=win):
                try:
                    if self.server.stop():
                        core.audit('llama_server', 'stopped')
                    status.configure(text='Остановлен')
                except Exception as exc:
                    messagebox.showerror('Ошибка', str(exc), parent=win)
        self.button(buttons, 'Выбрать EXE', select_exe).pack(side='left', padx=(0, 6))
        self.button(buttons, 'Выбрать GGUF', select_model).pack(side='left', padx=(0, 6))
        self.button(buttons, 'Запустить', start).pack(side='left', padx=(0, 6))
        self.button(buttons, 'Остановить', stop).pack(side='left')
        win.columnconfigure(1, weight=1)

    def runtime_setup_window(self):
        """Explicit, non-executing profile wizard with separate save approval."""
        win = tk.Toplevel(self.root)
        win.title('Мастер локального ИИ — CPU / Vulkan')
        win.geometry('770x470')
        win.configure(bg=BG)
        tk.Label(win, text='Профиль запуска (без автоматического запуска)', bg=BG, fg=ACCENT,
                 font=('Segoe UI', 13, 'bold')).pack(anchor='w', padx=16, pady=12)
        profiles = list(runtime_setup.PROFILES)
        chosen = tk.StringVar(value=profiles[0])
        selector = ttk.Combobox(win, values=profiles, textvariable=chosen, state='readonly', width=42)
        selector.pack(anchor='w', padx=16)
        explanation = tk.Label(win, bg=BG, fg=FG, justify='left', wraplength=720,
            text='CPU-профиль — самый совместимый. Vulkan-профили экспериментальные: RX 580 может не поддерживаться конкретной сборкой.\n'
                 'Настройка не скачивает модели и не запускает процесс.')
        explanation.pack(anchor='w', padx=16, pady=10)
        output = scrolledtext.ScrolledText(win, wrap='word', bg=PANEL, fg=FG, height=12,
                                           font=('Consolas', 10), state='disabled')
        output.pack(fill='both', expand=True, padx=16, pady=8)
        def preview():
            try:
                settings = runtime_setup.profile_settings(chosen.get(), self.settings.get('port', 8080))
                report = runtime_setup.runtime_report(self.settings)
                details = ('Предлагаемые параметры:\n' + '\n'.join(f'{k}: {v}' for k, v in settings.items())
                           + '\n\nДиагностика без сетевых запросов:\n' + report)
                output.configure(state='normal')
                output.delete('1.0', 'end')
                output.insert('1.0', details)
                output.configure(state='disabled')
            except (ValueError, OSError) as exc:
                messagebox.showerror('Профиль', str(exc), parent=win)
        def apply():
            try:
                changes = runtime_setup.profile_settings(chosen.get(), self.settings.get('port', 8080))
                info = '\n'.join(f'{k} = {v}' for k, v in changes.items())
                if not messagebox.askyesno('Подтверждение настроек',
                     'Сохранить параметры для следующего ручного запуска сервера?\n\n' + info +
                     '\n\nСейчас сервер НЕ запускается.', parent=win):
                    core.audit('runtime_profile', 'denied', chosen.get())
                    return
                self.settings.update({k: str(v) if k in ('gpu_layers','context','port') else v
                                      for k,v in changes.items()})
                core.save_config(self.settings)
                core.audit('runtime_profile', 'saved', chosen.get())
                messagebox.showinfo('Профиль', 'Настройки сохранены. Запускать сервер нужно отдельно.', parent=win)
                preview()
            except (ValueError, OSError) as exc:
                messagebox.showerror('Профиль', str(exc), parent=win)
        bar = tk.Frame(win, bg=BG)
        bar.pack(fill='x', padx=16, pady=(0, 12))
        self.button(bar, 'Проверить без запуска', preview).pack(side='left', padx=(0, 8))
        self.button(bar, 'Сохранить с подтверждением', apply).pack(side='left')
        preview()

    def text_window(self, title, text, editable=False):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry('850x620')
        win.configure(bg=BG)
        box = scrolledtext.ScrolledText(win, wrap='none', bg=PANEL, fg=FG,
                                       insertbackground=FG, font=('Consolas', 10), padx=12, pady=12)
        box.pack(fill='both', expand=True, padx=12, pady=12)
        box.insert('1.0', text)
        if not editable:
            box.configure(state='disabled')
        return win, box

    def workspace_root(self):
        root = self.settings.get('workspace', '')
        if not root:
            messagebox.showinfo('Рабочая папка', 'Сначала выберите рабочую папку.', parent=self.root)
            return None
        try:
            return workspace.normalized_root(root)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Рабочая папка', str(exc), parent=self.root)
            return None

    def choose_workspace(self):
        chosen = filedialog.askdirectory(parent=self.root, title='Разрешённая рабочая папка')
        if not chosen:
            return
        try:
            workspace.normalized_root(chosen)
            if self.approve('Предоставить доступ на чтение и подтверждаемые изменения только внутри папки?\n' + chosen):
                self.settings['workspace'] = chosen
                core.save_config(self.settings)
                self.print_chat('Система', 'Рабочая папка: ' + chosen)
        except Exception as exc:
            messagebox.showerror('Ошибка', str(exc), parent=self.root)

    def browse_workspace(self):
        root = self.workspace_root()
        if root is None:
            return
        try:
            files = workspace.list_files(root)
            self.text_window('Файлы рабочей папки', '\n'.join(f'{name}  ({size} байт)' for name, size in files) or '(папка пуста)')
            core.audit('list_workspace', 'done', str(root))
        except Exception as exc:
            messagebox.showerror('Ошибка', str(exc), parent=self.root)

    def pick_workspace_file(self):
        root = self.workspace_root()
        if root is None:
            return None
        filename = filedialog.askopenfilename(initialdir=str(root), parent=self.root,
                                             title='Выберите UTF-8 текстовый файл внутри рабочей папки')
        if not filename:
            return None
        try:
            workspace.safe_path(root, filename)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Доступ запрещён', str(exc), parent=self.root)
            core.audit('workspace_access', 'denied', str(exc))
            return None
        return filename

    def analyze_file(self):
        if self.busy:
            return
        filename = self.pick_workspace_file()
        if not filename:
            return
        question = simpledialog.askstring('Анализ файла', 'Что нужно выяснить о содержимом?',
                                          initialvalue='Найди ошибки и предложи улучшения.', parent=self.root)
        if not question:
            return
        try:
            payload = agent.build_file_question(self.workspace_root(), filename, question)
        except Exception as exc:
            messagebox.showerror('Ошибка чтения', str(exc), parent=self.root)
            return
        if not self.approve('Отправить содержимое файла в выбранный ИИ?\n' + filename +
                            '\nВАЖНО: облачный режим передаст данные провайдеру; проверьте настройку fallback.'):
            return
        conversations.add_message(self.current_conversation, 'user', 'Анализ файла: ' + Path(filename).name + '. ' + question)
        self.print_chat('Вы', 'Анализ: ' + Path(filename).name + ' — ' + question)
        messages = [{'role':'system','content':core.SYSTEM_PROMPT},
                    {'role':'user','content':payload}]
        self.set_busy(True, 'Анализ файла...')
        cfg, key = self.settings.copy(), self.api_key
        def work():
            try:
                result, provider = core.chat(cfg, messages, key)
                self.events.put(('answer', result, provider))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def edit_workspace_file(self):
        root = self.workspace_root()
        if root is None:
            return
        filename = self.pick_workspace_file()
        if not filename:
            return
        try:
            content = workspace.read_text(root, filename)
        except Exception as exc:
            messagebox.showerror('Ошибка', str(exc), parent=self.root)
            return
        win, box = self.text_window('Редактор — ' + Path(filename).name, content, editable=True)
        def preview():
            try:
                draft = workspace.draft_change(root, filename, box.get('1.0', 'end-1c'))
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
                return
            diff_win, _ = self.text_window('Проверка изменения — только после подтверждения', draft['diff'])
            def commit():
                if draft['diff'] == '(нет изменений)':
                    messagebox.showinfo('Редактор', 'Изменений нет.', parent=diff_win)
                    return
                if not messagebox.askyesno('Подтверждение записи', 'Вы просмотрели изменения?\n\nИзменить файл: ' + filename + '?', parent=diff_win):
                    core.audit('edit_file', 'denied', filename)
                    return
                try:
                    backup = workspace.apply_change(root, draft, core.ensure_dir() / 'backups')
                    core.audit('edit_file', 'done', filename + ' backup: ' + backup)
                    messagebox.showinfo('Сохранено', 'Файл обновлён. Резервная копия: ' + (backup or 'не нужна'), parent=diff_win)
                    diff_win.destroy()
                    win.destroy()
                except Exception as exc:
                    core.audit('edit_file', 'failed', str(exc))
                    messagebox.showerror('Ошибка записи', str(exc), parent=diff_win)
            self.button(diff_win, 'Подтвердить и сохранить', commit).pack(pady=(0, 12))
        self.button(win, 'Просмотреть изменения', preview).pack(pady=(0, 12))

    def notes(self):
        win = tk.Toplevel(self.root)
        win.title('Личные заметки — локально')
        win.geometry('720x530')
        win.configure(bg=BG)
        pane = tk.Frame(win, bg=BG)
        pane.pack(fill='both', expand=True, padx=15, pady=15)
        listing = tk.Listbox(pane, bg=PANEL, fg=FG, width=30, selectbackground=ACCENT, selectforeground=BG)
        listing.pack(side='left', fill='y')
        editor = scrolledtext.ScrolledText(pane, bg=PANEL, fg=FG, insertbackground=FG, wrap='word')
        editor.pack(side='left', fill='both', expand=True, padx=(12, 0))
        note_ids = []
        def refresh():
            listing.delete(0, 'end')
            note_ids.clear()
            for nid, title, body in core.list_notes():
                note_ids.append((nid, title, body))
                listing.insert('end', title)
        def select(event=None):
            selected = listing.curselection()
            if selected:
                editor.delete('1.0', 'end')
                editor.insert('1.0', note_ids[selected[0]][2])
        listing.bind('<<ListboxSelect>>', select)
        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill='x', padx=15, pady=(0, 12))
        def add():
            name = simpledialog.askstring('Новая заметка', 'Название:', parent=win)
            if name:
                core.add_note(name, editor.get('1.0', 'end-1c'))
                core.audit('add_note', 'done', name)
                editor.delete('1.0', 'end')
                refresh()
        def delete():
            selected = listing.curselection()
            if selected and messagebox.askyesno('Удаление', 'Удалить выбранную заметку?', parent=win):
                core.remove_note(note_ids[selected[0]][0])
                refresh()
        self.button(buttons, 'Сохранить как новую', add).pack(side='left')
        self.button(buttons, 'Удалить выбранную', delete).pack(side='left', padx=8)
        refresh()

    def show_audit(self):
        rows = core.get_audit()
        text = '\n'.join(f'{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M:%S} | {action} | {status} | {details}'
                         for ts,action,status,details in rows)
        self.text_window('Журнал операций', text or 'Журнал пуст')

    def check_model(self):
        if self.busy:
            return
        self.set_busy(True, 'Проверка локального сервера...')
        url = self.settings['local_url']
        def work():
            try:
                models = diagnostics.probe_local(url)
                self.events.put(('info', 'Локальный ИИ отвечает. Модели: ' + ', '.join(models or ['не указаны'])))
                core.audit('probe_local', 'done', url)
            except Exception as exc:
                self.events.put(('info', 'Локальный ИИ пока не отвечает: ' + str(exc)))
                core.audit('probe_local', 'failed', str(exc))
        threading.Thread(target=work, daemon=True).start()

    def export_chat(self):
        filename = filedialog.asksaveasfilename(parent=self.root, title='Экспорт диалога',
                 defaultextension='.json', filetypes=[('JSON', '*.json')])
        if filename and self.approve('Экспортировать историю в открытый JSON-файл?\n' + filename):
            try:
                count = conversations.export(self.current_conversation, filename)
                core.audit('export_chat', 'done', 'messages: ' + str(count))
                messagebox.showinfo('Экспорт', f'Экспортировано сообщений: {count}', parent=self.root)
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=self.root)

    def plan_changes(self):
        """An LLM proposes inert JSON; human sees EVERY diff and approves each commit."""
        if self.busy:
            return
        root = self.workspace_root()
        if root is None:
            return
        request = simpledialog.askstring('План изменений ИИ',
            'Что нужно изменить в текстовых файлах рабочей папки?', parent=self.root)
        if not request:
            return
        files = workspace.list_files(root, limit=100)
        # Deliberately send file NAMES only, never contents without further consent.
        context = '\n'.join(name for name, _ in files)[:8000]
        model_prompt = (proposals.PLANNER_INSTRUCTION + '\nФайлы в рабочей папке (только имена):\n' +
                        context + '\nЗадача пользователя:\n' + request)
        if not self.approve('Отправить задачу и ИМЕНА файлов выбранному ИИ?\n'
                            'В облачном режиме эти данные поступят внешнему провайдеру.\n'
                            'Содержимое файлов не передаётся.'):
            return
        self.set_busy(True, 'ИИ подготавливает план...')
        cfg, key = self.settings.copy(), self.api_key
        def worker():
            try:
                answer, provider = core.chat(cfg, [
                    {'role':'system','content':core.SYSTEM_PROMPT},
                    {'role':'user','content':model_prompt}], key)
                self.events.put(('plan', answer, provider))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def review_plan(self, answer, provider):
        root = self.workspace_root()
        if root is None:
            return
        try:
            plan = proposals.parse_proposal(answer)
            ids = review_queue.enqueue(root,plan)
        except Exception as exc:
            core.audit('agent_plan', 'rejected', str(exc))
            self.text_window('Некорректный план ИИ', str(exc) + '\n\n' + answer[:8000])
            return
        core.audit('agent_plan', 'queued', f'provider={provider}; steps={len(ids)}')
        self.print_chat('ИИ — план ('+provider+')', plan['summary'] +
                        f'\nНа проверку поставлено этапов: {len(ids)}. Файлы не изменены.')
        if ids:
            self.review_queue_window()

    def review_queue_window(self):
        win = tk.Toplevel(self.root)
        win.title('Очередь подтверждений — каждое изменение отдельно')
        win.geometry('840x490')
        win.configure(bg=BG)
        listing = tk.Listbox(win,bg=PANEL,fg=FG,selectbackground=ACCENT,selectforeground=BG)
        listing.pack(fill='both',expand=True,padx=12,pady=12)
        rows=[]
        def refresh():
            rows[:] = review_queue.pending()
            listing.delete(0,'end')
            for sid,batch,path,state,root in rows:
                listing.insert('end',f'#{sid} [{state}] {path}  — {Path(root).name}')
        def selected():
            idx=listing.curselection()
            return rows[idx[0]] if idx else None
        def check():
            row=selected()
            if not row:
                return
            sid=row[0]
            try:
                root,name,draft=review_queue.preview(sid)
            except Exception as exc:
                messagebox.showerror('Ошибка',str(exc),parent=win)
                return
            preview,_=self.text_window(f'Этап #{sid}: {name}',draft['diff'])
            def apply():
                if draft['diff']=='(нет изменений)':
                    messagebox.showinfo('Нет изменений','Содержимое совпадает.',parent=preview)
                    return
                if not messagebox.askyesno('Разрешение',
                        f'Записать ТОЛЬКО файл {name}?\nПредпросмотр изменений показан выше.',parent=preview):
                    core.audit('queue_step','denied',str(sid))
                    return
                try:
                    review_queue.decide(sid,'apply',approved=True,draft=draft,backup_dir=core.ensure_dir()/'backups')
                    core.audit('queue_step','applied',str(sid))
                    refresh()
                    preview.destroy()
                except Exception as exc:
                    core.audit('queue_step','failed',f'{sid}: {exc}')
                    messagebox.showerror('Ошибка записи',str(exc),parent=preview)
            self.button(preview,'Подтвердить запись этого файла',apply).pack(pady=10)
        def reject():
            row=selected()
            if row and row[3]=='pending' and messagebox.askyesno('Отклонение',
                    'Отклонить только этот этап?',parent=win):
                try:
                    review_queue.decide(row[0],'reject',approved=True)
                    core.audit('queue_step','rejected',str(row[0]))
                    refresh()
                except Exception as exc:
                    messagebox.showerror('Ошибка',str(exc),parent=win)
        bar=tk.Frame(win,bg=BG)
        bar.pack(fill='x',padx=12,pady=8)
        for name,fun in [('Просмотреть выбранное',check),('Отклонить выбранное',reject),('Обновить',refresh)]:
            self.button(bar,name,fun).pack(side='left',padx=5)
        refresh()

    def search_dialogues(self):
        term=simpledialog.askstring('Поиск по диалогам','Найти фразу (2–160 символов):',parent=self.root)
        if term is None:
            return
        try:
            rows=conversations.search_messages(term)
        except ValueError as exc:
            messagebox.showerror('Ошибка поиска',str(exc),parent=self.root)
            return
        win=tk.Toplevel(self.root)
        win.title('Поиск по переписке — локально')
        win.geometry('850x520')
        win.configure(bg=BG)
        pane=tk.Listbox(win,bg=PANEL,fg=FG,selectbackground=ACCENT,selectforeground=BG)
        pane.pack(fill='both',expand=True,padx=12,pady=12)
        for mid,cid,title,role,fragment,ts in rows:
            pane.insert('end',f'#{cid} {title} — {role}: {fragment[:180].replace(chr(10)," ")}')
        def jump():
            chosen=pane.curselection()
            if not chosen or self.busy:
                return
            self.refresh_conversations(rows[chosen[0]][1])
            self.reload_conversation()
            win.destroy()
        self.button(win,'Открыть найденный диалог',jump).pack(pady=8)
        tk.Label(win,text=f'Найдено: {len(rows)} (по последним 10 000 сообщениям)',
                 bg=BG,fg=FG).pack(pady=(0,9))

    def manage_backups(self):
        root = self.workspace_root()
        if root is None:
            return
        backup_dir = core.ensure_dir() / 'backups'
        rows = maintenance.backup_inventory(backup_dir)
        if not rows:
            messagebox.showinfo('Резервные копии', 'Резервных копий пока нет.', parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title('Резервные копии — ручное восстановление')
        win.geometry('720x460')
        listing = tk.Listbox(win, bg=PANEL, fg=FG, selectbackground=ACCENT, selectforeground=BG)
        listing.pack(fill='both', expand=True, padx=12, pady=12)
        for name, size, ts in rows:
            listing.insert('end', f'{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M} — {name} ({size} байт)')
        tk.Label(win, text='Выбери резервную копию и целевой файл внутри рабочей папки.',
                 wraplength=680).pack(pady=4)
        def restore():
            chosen = listing.curselection()
            if not chosen:
                return
            backup_name = rows[chosen[0]][0]
            target = filedialog.askopenfilename(parent=win, initialdir=str(root),
                        title='КАКОЙ файл восстановить из этой копии?')
            if not target:
                return
            try:
                source = (backup_dir / backup_name).resolve(strict=True)
                if source.parent != backup_dir.resolve() or source.stat().st_size > workspace.MAX_TEXT_BYTES:
                    raise ValueError('Некорректная резервная копия')
                draft = workspace.draft_change(root, target, source.read_text(encoding='utf-8-sig'))
                preview, _ = self.text_window('Проверить восстановление: ' + target, draft['diff'])
                def apply():
                    if not messagebox.askyesno('Восстановление', 'Применить показанный diff к файлу?\n' + target,
                                               parent=preview):
                        core.audit('restore_backup', 'denied', target)
                        return
                    try:
                        workspace.apply_change(root, draft, backup_dir)
                        core.audit('restore_backup', 'done', target)
                        preview.destroy()
                        messagebox.showinfo('Готово', 'Восстановлено. Текущее состояние также сохранено в backup.', parent=win)
                    except Exception as exc:
                        core.audit('restore_backup', 'failed', str(exc))
                        messagebox.showerror('Ошибка', str(exc), parent=preview)
                self.button(preview, 'Подтвердить восстановление', apply).pack(pady=10)
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
        self.button(win, 'Просмотреть восстановление', restore).pack(pady=8)

    def backup_data_window(self):
        win = tk.Toplevel(self.root)
        win.title('Резервное копирование данных')
        win.geometry('680x340')
        win.configure(bg=BG)
        description = ('Сохраняет настройки и согласованный снимок SQLite в ZIP.\n'
                       'Не включает модели, исходники проектов и API-ключи.\n'
                       'Архив НЕ зашифрован: храните его в защищённом месте.\n'
                       'Автоматическое восстановление намеренно не поддерживается.')
        tk.Label(win, text=description, bg=BG, fg=FG, justify='left',
                 font=('Segoe UI', 11)).pack(padx=15, pady=15)
        def export():
            path = filedialog.asksaveasfilename(parent=win, title='Новый архив PersonalAI',
                        defaultextension='.zip', filetypes=[('ZIP', '*.zip')],
                        initialfile='PersonalAI-Backup.zip')
            if not path or not self.approve('Создать незашифрованную копию персональных данных?\n' + path):
                return
            try:
                result = data_portability.export_backup(path)
                core.audit('export_backup', 'done', str(Path(path).name))
                messagebox.showinfo('Архив создан',
                    f"Резервная копия проверена. База: {result['database_bytes']} байт.", parent=win)
            except Exception as exc:
                messagebox.showerror('Ошибка копирования', str(exc), parent=win)
        def verify():
            path = filedialog.askopenfilename(parent=win, title='Проверить архив PersonalAI',
                                               filetypes=[('ZIP', '*.zip')])
            if not path: return
            try:
                result = data_portability.verify_backup(path)
                messagebox.showinfo('Архив проверен',
                   f"Контрольные суммы совпадают.\nСоздан: {result['created_utc']}", parent=win)
            except Exception as exc:
                messagebox.showerror('Архив повреждён или не поддерживается', str(exc), parent=win)
        self.button(win, 'Создать архив', export).pack(pady=8)
        self.button(win, 'Проверить ZIP', verify).pack(pady=8)

    def show_storage(self):
        try:
            stats = maintenance.storage_statistics()
        except Exception as exc:
            messagebox.showerror('Ошибка', str(exc), parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title('Хранилище и приватность')
        win.geometry('560x310')
        win.configure(bg=BG)
        text = (f"Сообщений: {conversations.count()} (новый формат)\nЗаметок: {stats['notes']}\n"
                f"Записей аудита: {stats['audit']}\nКопий (первые 400): {stats['backups']}\n"
                f"Размер БД: {stats['database_bytes']} байт\n"
                f"Размер копий (первые 400): {stats['backup_bytes']} байт\n"
                'Внимание: база данных и резервные копии НЕ зашифрованы.')
        tk.Label(win, text=text, bg=BG, fg=FG, justify='left', font=('Segoe UI', 11)).pack(padx=20,pady=18)
        def purge():
            from datetime import timedelta
            days = simpledialog.askinteger('Хранение истории',
                'Удалить сообщения старше скольких дней? (1–3650)', minvalue=1, maxvalue=3650, parent=win)
            if days is None:
                return
            if not messagebox.askyesno('Удаление истории',
                f'Безвозвратно удалить сообщения старше {days} дней? Заметки и журнал останутся.', parent=win):
                return
            try:
                import time
                n = conversations.purge_before(int(time.time())-days*86400)
                core.audit('purge_history', 'done', str(n))
                messagebox.showinfo('Готово', f'Удалено сообщений: {n}', parent=win)
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
        self.button(win, 'Очистить старую переписку', purge).pack(pady=6)
        def legacy_purge():
            if not messagebox.askyesno('Удаление старого формата',
                    'Удалить legacy-таблицу истории? Современные диалоги останутся.\n'
                    'Перед операцией рекомендуется сделать резервную копию базы.', parent=win):
                return
            if not self.approve('Окончательно удалить все записи старого формата history?'):
                return
            try:
                n=maintenance.clear_legacy_history(approved=True)
                core.audit('purge_legacy_history','done',str(n))
                messagebox.showinfo('Готово',f'Удалено записей старого формата: {n}',parent=win)
            except Exception as exc:
                messagebox.showerror('Ошибка',str(exc),parent=win)
        self.button(win,'Очистить импортированную историю старого формата',legacy_purge).pack(pady=6)

    def manage_tasks(self):
        window = tk.Toplevel(self.root)
        window.title('Задачи — только ручное управление')
        window.geometry('720x480')
        frame = tk.Frame(window)
        frame.pack(fill='both', expand=True, padx=12, pady=12)
        item_list = tk.Listbox(frame, height=17)
        item_list.pack(fill='both', expand=True)
        records = []

        def refresh():
            records[:] = tasks.list_all()
            item_list.delete(0, 'end')
            for task_id, title, description, state in records:
                item_list.insert('end', f'#{task_id} [{state}] {title}')

        def create_task():
            title = simpledialog.askstring('Новая задача', 'Название задачи:', parent=window)
            if title is None:
                return
            description = simpledialog.askstring('Описание', 'Описание (необязательно):', parent=window) or ''
            try:
                task_id = tasks.create(title, description)
                core.audit('task_create', 'approved', str(task_id))
                refresh()
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=window)

        def selected():
            selection = item_list.curselection()
            return records[selection[0]] if selection else None

        def update_task():
            task = selected()
            if not task:
                return
            new_state = simpledialog.askstring('Статус задачи',
                        'planned / in_progress / done / cancelled', initialvalue=task[3], parent=window)
            if new_state is None:
                return
            try:
                tasks.set_state(task[0], new_state.strip())
                core.audit('task_status', 'approved', f'{task[0]}: {new_state}')
                refresh()
            except ValueError as exc:
                messagebox.showerror('Ошибка', str(exc), parent=window)

        def delete_task():
            task = selected()
            if task and messagebox.askyesno('Удаление', 'Удалить задачу #' + str(task[0]) + '?', parent=window):
                tasks.delete(task[0])
                core.audit('task_delete', 'approved', str(task[0]))
                refresh()

        bar = tk.Frame(frame)
        bar.pack(fill='x', pady=6)
        for name, cmd in [('Добавить', create_task), ('Изменить статус', update_task),
                          ('Удалить', delete_task), ('Обновить', refresh)]:
            tk.Button(bar, text=name, command=cmd).pack(side='left', padx=4)
        refresh()

    def windows_apps_window(self):
        win = tk.Toplevel(self.root)
        win.title('Программы Windows — разрешённые действия')
        win.geometry('540x345')
        tk.Label(win, text='Только три встроенные программы Windows.\n'
                 'Никаких команд PowerShell, аргументов и пользовательских EXE.',
                 justify='left').pack(anchor='w', padx=16, pady=12)
        rows = windows_tools.list_applications()
        choices = tk.Listbox(win, height=5, exportselection=False)
        choices.pack(fill='x', padx=16, pady=6)
        for key, title in rows:
            choices.insert('end', title)

        def start():
            sel = choices.curselection()
            if not sel:
                return
            app_id, title = rows[sel[0]]
            if not messagebox.askyesno('Разрешение на запуск',
                    f'Разрешить PersonalAI открыть «{title}»?\n'
                    'Операция не передаёт данные облачному ИИ.', parent=win):
                core.audit('windows_app_launch', 'denied', app_id)
                return
            try:
                windows_tools.launch(app_id, approved=True)
                core.audit('windows_app_launch', 'approved', app_id)
                messagebox.showinfo('Запуск', f'Запрошен запуск «{title}».', parent=win)
            except Exception as exc:
                core.audit('windows_app_launch', 'failed', app_id)
                messagebox.showerror('Ошибка запуска', str(exc), parent=win)

        tk.Button(win, text='Открыть после подтверждения', command=start).pack(pady=12)

    def workflows_window(self):
        win = tk.Toplevel(self.root)
        win.title('Контролируемые сценарии — каждый этап подтверждается')
        win.geometry('850x610')
        info = tk.Label(win, text='Никаких команд Windows и автоматического перехода к следующему этапу.', wraplength=800)
        info.pack(fill='x', padx=12, pady=8)
        left = tk.Listbox(win, height=10)
        left.pack(fill='x', padx=12)
        view = scrolledtext.ScrolledText(win, wrap='word', height=18)
        view.pack(fill='both', expand=True, padx=12, pady=8)
        rows = []

        def refresh():
            rows[:] = workflows.list_all()
            left.delete(0, 'end')
            for wid, root, title, status in rows:
                left.insert('end', f'#{wid} [{status}] {title} — {root}')

        def selected_id():
            idx = left.curselection()
            return rows[idx[0]][0] if idx else None

        def show():
            wid = selected_id()
            if wid is None:
                return
            header, steps = workflows.details(wid)
            text = workflows.preview(wid) + '\n\n'
            for sid, position, kind, status, result in steps:
                text += f'\n[{position}] {workflows.LABELS.get(kind, kind)} — {status}\n{result[:8000]}\n'
            view.delete('1.0', 'end')
            view.insert('1.0', text)

        def create_scenario():
            try:
                root = self.workspace_root()
            except Exception as exc:
                messagebox.showerror('Сценарии', str(exc), parent=win)
                return
            choices = list(workflows.TEMPLATES)
            choice = simpledialog.askstring('Новый сценарий',
                'Выберите шаблон: audit_snapshot / audit_only / snapshot_only',
                initialvalue='audit_snapshot', parent=win)
            if choice is None:
                return
            if choice not in choices:
                messagebox.showerror('Сценарии', 'Неизвестный шаблон', parent=win)
                return
            if not messagebox.askyesno('Создать сценарий',
                    f'Создать «{workflows.TEMPLATES[choice][0]}» для папки {root}?', parent=win):
                return
            workflows.create(root, choice)
            refresh()

        def create_custom():
            try:
                root = self.workspace_root()
            except Exception as exc:
                messagebox.showerror('Сценарии', str(exc), parent=win)
                return
            dialog = tk.Toplevel(win)
            dialog.title('Конструктор безопасного сценария')
            dialog.geometry('680x440')
            tk.Label(dialog, text='Введите JSON-план. Разрешены только audit и snapshot (1–8 этапов).\n'
                        'Код из этого окна не выполняется; создание плана не запускает этапы.',
                     justify='left').pack(fill='x', padx=12, pady=8)
            editor = scrolledtext.ScrolledText(dialog, wrap='word', height=14)
            editor.pack(fill='both', expand=True, padx=12)
            editor.insert('1.0', '{\n  "title": "Проверка проекта",\n  "steps": ["audit", "snapshot"]\n}')
            def submit_plan():
                raw = editor.get('1.0', 'end').strip()
                try:
                    explanation = workflows.preview_plan(root, raw)
                except Exception as exc:
                    messagebox.showerror('Недопустимый план', str(exc), parent=dialog)
                    return
                if not messagebox.askyesno('Подтвердить создание плана', explanation, parent=dialog):
                    return
                try:
                    workflows.create_from_plan(root, raw, approved=True)
                    refresh()
                    dialog.destroy()
                except Exception as exc:
                    messagebox.showerror('Сценарии', str(exc), parent=dialog)
            tk.Button(dialog, text='Просмотреть и создать (с подтверждением)',
                      command=submit_plan).pack(padx=12, pady=9)

        def advance():
            wid = selected_id()
            if wid is None:
                return
            explanation = workflows.preview(wid)
            if not workflows.next_step(wid):
                messagebox.showinfo('Сценарий', explanation, parent=win)
                return
            if not messagebox.askyesno('Подтвердить отдельный этап', explanation, parent=win):
                return
            try:
                result = workflows.execute_step(wid, approved=True)
                refresh()
                for index, row in enumerate(rows):
                    if row[0] == wid:
                        left.selection_set(index)
                        break
                show()
                messagebox.showinfo('Этап выполнен', result[:1000], parent=win)
            except Exception as exc:
                messagebox.showerror('Ошибка сценария', str(exc), parent=win)
                refresh()

        def cancel_scenario():
            wid = selected_id()
            if wid is None:
                return
            if messagebox.askyesno('Отмена', f'Отменить оставшиеся этапы сценария #{wid}?', parent=win):
                try:
                    workflows.cancel(wid, approved=True)
                    refresh()
                except Exception as exc:
                    messagebox.showerror('Сценарий', str(exc), parent=win)

        def recover():
            wid = selected_id()
            if wid is None:
                return
            stale = [x for x in workflows.list_interrupted() if x[1] == wid]
            if not stale:
                messagebox.showinfo('Восстановление',
                    'Нет прерванных этапов старше 24 часов.', parent=win)
                return
            warning = ('Прерванный этап может уже иметь частичный результат.\n'
                       'Проверьте файлы и снимки перед повторным выполнением.\n\n'
                       'Отметить прерванный этап как ошибочный без повторного запуска?')
            if not messagebox.askyesno('Восстановить статус', warning, parent=win):
                return
            try:
                workflows.mark_interrupted(wid, approved=True)
                refresh()
                messagebox.showinfo('Восстановление',
                    'Статус восстановлен. Повторять операцию можно только отдельным разрешением.', parent=win)
            except Exception as exc:
                messagebox.showerror('Восстановление', str(exc), parent=win)

        bar = tk.Frame(win)
        bar.pack(fill='x', padx=12, pady=8)
        for title, action in [('Создать', create_scenario), ('Конструктор', create_custom), ('Просмотр', show),
                              ('Подтвердить один этап', advance), ('Отменить', cancel_scenario), ('Восстановить', recover), ('Обновить', refresh)]:
            tk.Button(bar, text=title, command=action).pack(side='left', padx=4)
        left.bind('<<ListboxSelect>>', lambda event: show())
        refresh()

    def dictation(self):
        if self.busy:
            return
        folder = self.settings.get('vosk_model_dir', '').strip()
        if not folder:
            folder = filedialog.askdirectory(title='Выберите распакованную офлайн Vosk-модель')
            if not folder:
                return
            self.settings['vosk_model_dir'] = folder
            core.save_config(self.settings)
        if not self.approve('Записать микрофон на 8 секунд для ЛОКАЛЬНОГО распознавания речи?'):
            return
        self.set_busy(True, 'Запись микрофона (8 секунд)...')
        def worker():
            try:
                result = recognition.transcribe_once(folder, seconds=8)
                self.events.put(('dictation', result))
                core.audit('dictation', 'completed', 'offline; chars=' + str(len(result)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def model_download(self):
        if self.busy:
            return
        url = simpledialog.askstring('Загрузка GGUF', 'HTTPS URL модели GGUF:', parent=self.root)
        if not url:
            return
        checksum = simpledialog.askstring('Контрольная сумма', 'SHA-256 от доверенного источника (64 символа):', parent=self.root)
        if not checksum:
            return
        path = filedialog.asksaveasfilename(title='Сохранить модель GGUF', defaultextension='.gguf',
                                            filetypes=[('GGUF', '*.gguf')])
        if not path:
            return
        try:
            downloads.validate(url, checksum.strip(), path)
        except Exception as exc:
            messagebox.showerror('Некорректная загрузка', str(exc), parent=self.root)
            return
        if not self.approve('Скачать по HTTPS модель в ' + path +
                            '\nПроверить SHA-256 перед установкой (не более 12 ГБ)?'):
            return
        self.set_busy(True, 'Скачивание модели...')
        def worker():
            try:
                size = downloads.download(url, checksum.strip(), path,
                        progress=lambda count: self.events.put(('download_progress', count)))
                core.audit('model_download', 'completed', f'bytes={size}; destination={path}')
                self.events.put(('download_complete', path, size))
            except Exception as exc:
                core.audit('model_download', 'failed', str(exc))
                self.events.put(('error', 'Загрузка не удалась: ' + str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def models_window(self):
        """Only scans a directory manually chosen by the user; no network requests."""
        win = tk.Toplevel(self.root)
        win.title('Мои модели GGUF — локальный каталог')
        win.geometry('900x540')
        win.configure(bg=BG)
        tk.Label(win, text='Выберите папку: просматриваются только файлы GGUF в её корне.',
                 bg=BG, fg=FG).pack(anchor='w', padx=12, pady=(12, 4))
        folder_var = tk.StringVar(value=self.settings.get('models_folder', ''))
        ttk.Entry(win, textvariable=folder_var, width=105, state='readonly').pack(fill='x', padx=12)
        rows = []
        tree = ttk.Treeview(win, columns=('size', 'format', 'hint'), show='headings', selectmode='browse')
        for key, label, width in [('size', 'ГиБ', 85), ('format', 'GGUF', 75), ('hint', 'Имя модели', 610)]:
            tree.heading(key, text=label)
            tree.column(key, width=width)
        tree.pack(fill='both', expand=True, padx=12, pady=8)
        state = tk.Label(win, text='Папка ещё не проверена.', bg=BG, fg=FG)
        state.pack(anchor='w', padx=12)

        def scan():
            nonlocal rows
            try:
                result = model_inventory.inventory(folder_var.get())
                rows = result['models']
                for item in tree.get_children():
                    tree.delete(item)
                for i, model in enumerate(rows):
                    tree.insert('', 'end', iid=str(i), values=(f"{model['size']/1024**3:.2f}",
                               model['version'], model['name']))
                state.configure(text=f"Найдено {len(rows)} GGUF, пропущено {result['skipped']}. Ничего не загружалось в интернет.")
                core.audit('model_inventory', 'inspected', f"models={len(rows)} skipped={result['skipped']}")
            except (ValueError, OSError) as exc:
                messagebox.showerror('Модели', str(exc), parent=win)

        def choose():
            directory = filedialog.askdirectory(parent=win, title='Каталог GGUF-моделей')
            if directory:
                folder_var.set(directory)
                self.settings['models_folder'] = directory
                core.save_config(self.settings)
                scan()

        def selected():
            ids = tree.selection()
            if not ids:
                messagebox.showinfo('Модели', 'Выберите строку модели.', parent=win)
                return None
            return rows[int(ids[0])]

        def details():
            item = selected()
            if item:
                text = (f"Модель: {item['name']}\nПуть: {item['path']}\n"
                        f"Размер: {item['size']/1024**3:.2f} ГиБ\nВерсия GGUF: {item['version']}\n\n"
                        + model_inventory.guidance(item['size']))
                messagebox.showinfo('Информация о модели', text, parent=win)

        def use_model():
            item = selected()
            if not item:
                return
            if not messagebox.askyesno('Выбор модели',
                      'Установить выбранный путь GGUF в настройки сервера?\nМодель НЕ запускается.\n' + item['path'], parent=win):
                return
            self.settings['model_file'] = item['path']
            core.save_config(self.settings)
            core.audit('model_select', 'approved', item['name'])
            state.configure(text='Путь сохранён. Для запуска откройте «Сервер ИИ».')

        def verify():
            item = selected()
            if not item:
                return
            if not messagebox.askyesno('SHA-256', 'Прочитать выбранный файл полностью для расчёта SHA-256?\n'+item['name'], parent=win):
                return
            state.configure(text='Вычисление SHA-256...')
            def work():
                try:
                    digest = model_inventory.checksum(item['path'])
                    self.root.after(0, lambda: (state.configure(text='SHA-256: '+digest),
                       core.audit('model_checksum', 'completed', item['name'])))
                except Exception as exc:
                    detail = str(exc)
                    self.root.after(0, lambda: messagebox.showerror('SHA-256', detail, parent=win))
            threading.Thread(target=work, daemon=True).start()

        buttons = tk.Frame(win, bg=BG)
        buttons.pack(anchor='w', padx=12, pady=(0, 12))
        for label, callback in [('Выбрать папку', choose), ('Обновить', scan),
                 ('Сведения', details), ('Выбрать для сервера', use_model), ('Проверить SHA-256', verify)]:
            self.button(buttons, label, callback).pack(side='left', padx=(0, 8))

    def speak_answer(self):
        if not self.last_answer:
            messagebox.showinfo('Озвучивание', 'Пока нет ответа для озвучивания.', parent=self.root)
            return
        def work():
            try:
                voice.say_windows(self.last_answer)
                self.events.put(('speak_done', 'Ответ озвучен'))
            except Exception as exc:
                self.events.put(('speak_done', 'Озвучивание недоступно: ' + str(exc)))
        threading.Thread(target=work, daemon=True).start()


    def audit_project_window(self):
        """Run a read-only local scan in a worker; never send project data to AI."""
        if self.busy:
            return
        root = self.workspace_root()
        if root is None:
            return
        self.set_busy(True, 'Локальный аудит проекта...')
        def worker():
            try:
                report = project_audit.scan(root)
                self.events.put(('project_audit', project_audit.render(report)))
                core.audit('project_audit', 'done', 'files=' + str(report['scanned']))
            except Exception as exc:
                self.events.put(('error', 'Ошибка аудита: ' + str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def project_snapshots_window(self):
        """User-initiated local hash snapshots; no project content sent to a model."""
        root = self.workspace_root()
        if root is None:
            return
        win = tk.Toplevel(self.root)
        win.title('Снимки проекта — контроль изменений')
        win.geometry('850x600')
        win.configure(bg=BG)
        tk.Label(win, text='Снимки содержат только пути, размеры и SHA-256. Файлы не копируются.',
                 bg=BG, fg=FG).pack(anchor='w', padx=12, pady=10)
        listing = tk.Listbox(win, selectmode='extended', bg=PANEL, fg=FG, selectbackground=ACCENT, selectforeground=BG, height=9)
        listing.pack(fill='x', padx=12, pady=(0,8))
        output = scrolledtext.ScrolledText(win, bg=PANEL, fg=FG, insertbackground=FG, wrap='none')
        output.pack(fill='both', expand=True, padx=12, pady=8)
        records = []
        def refresh():
            records[:] = project_snapshots.list_all(root)
            listing.delete(0, 'end')
            for sid, created, _root, label in records:
                listing.insert('end', f'#{sid} — {datetime.fromtimestamp(created).strftime("%d.%m.%Y %H:%M")} — {label}')
        def selected():
            if not listing.curselection():
                messagebox.showinfo('Снимки', 'Выберите снимок.', parent=win)
                return None
            return records[listing.curselection()[0]][0]
        def put(text):
            output.delete('1.0','end')
            output.insert('1.0',text)
        def make():
            label = simpledialog.askstring('Новый снимок', 'Название снимка:', parent=win)
            if not label:
                return
            try:
                sid, snapshot = project_snapshots.create(root, label)
                core.audit('project_snapshot', 'created', f'id={sid}; files={len(snapshot["files"])}')
                put(f'Снимок #{sid} сохранён. Файлов: {len(snapshot["files"])}; пропущено: {snapshot["skipped"]}; ограничение: {snapshot["truncated"]}.')
                refresh()
            except Exception as exc:
                messagebox.showerror('Снимки', str(exc), parent=win)
        def check():
            sid = selected()
            if sid is None:
                return
            try:
                _root, label, diff, current = project_snapshots.compare_to_disk(sid)
                put(f'Сравнение с текущей рабочей папкой: {label}\nФайлов сейчас: {len(current["files"])}\n\n' + project_snapshots.render_comparison(diff))
                core.audit('project_snapshot', 'compared', f'id={sid}')
            except Exception as exc:
                messagebox.showerror('Снимки', str(exc), parent=win)
        def compare_two():
            indices = listing.curselection()
            if len(indices) != 2:
                messagebox.showinfo('Снимки', 'Выберите ровно два снимка (Ctrl+щелчок).', parent=win)
                return
            first, second = sorted((records[idx][0] for idx in indices))
            try:
                base1, label1, old = project_snapshots.load(first)
                base2, label2, new = project_snapshots.load(second)
                if base1 != base2:
                    raise ValueError('Нельзя сравнить снимки разных рабочих папок')
                diff = project_snapshots.compare(old, new)
                put(f'Сравнение снимков #{first} ({label1}) → #{second} ({label2})\n\n' + project_snapshots.render_comparison(diff))
                core.audit('project_snapshot', 'compared_two', f'{first}:{second}')
            except Exception as exc:
                messagebox.showerror('Снимки', str(exc), parent=win)
        def export_report():
            report = output.get('1.0','end-1c')
            if not report.strip():
                messagebox.showinfo('Снимки', 'Сначала выполните сравнение.', parent=win)
                return
            path = filedialog.asksaveasfilename(parent=win, title='Сохранить отчёт',
                                                 defaultextension='.txt', filetypes=[('Текстовый отчёт', '*.txt')])
            if path:
                try:
                    Path(path).write_text(report, encoding='utf-8')
                    core.audit('project_snapshot', 'report_exported', 'text report')
                except OSError as exc:
                    messagebox.showerror('Сохранение отчёта', str(exc), parent=win)
        def remove():
            sid = selected()
            if sid is not None and messagebox.askyesno('Удалить снимок', f'Удалить снимок #{sid}? Файлы проекта не изменятся.', parent=win):
                project_snapshots.delete(sid)
                core.audit('project_snapshot', 'deleted', f'id={sid}')
                refresh()
        bar = tk.Frame(win,bg=BG)
        bar.pack(fill='x', padx=12, pady=10)
        for index, (label, action) in enumerate([('Создать снимок',make),('Сравнить с диском',check),('Сравнить два',compare_two),('Экспорт отчёта',export_report),('Удалить снимок',remove),('Обновить',refresh)]):
            if index == 3:
                bar = tk.Frame(win,bg=BG)
                bar.pack(fill='x', padx=12, pady=(0,10))
            self.button(bar,label,action).pack(side='left',padx=(0,5))
        refresh()

    def project_context_window(self):
        """Select and explicitly approve files before sending data to the configured model."""
        if self.busy:
            return
        root = self.workspace_root()
        if root is None:
            return
        win = tk.Toplevel(self.root)
        win.title('Контекст проекта — локальный поиск и выбор файлов')
        win.geometry('850x620')
        win.configure(bg=BG)
        top = tk.Frame(win, bg=BG)
        top.pack(fill='x', padx=12, pady=8)
        tk.Label(top, text='Фильтр имён:', bg=BG, fg=FG).pack(side='left')
        filt = tk.Entry(top, bg=PANEL, fg=FG, insertbackground=FG)
        filt.pack(side='left', fill='x', expand=True, padx=8)
        listing = tk.Listbox(win, selectmode='extended', bg=PANEL, fg=FG,
                             selectbackground=ACCENT, selectforeground=BG)
        listing.pack(fill='both', expand=True, padx=12)
        visible = []
        def refresh():
            try:
                visible[:] = project_context.discover(root, filt.get())
                listing.delete(0, 'end')
                for name, size in visible:
                    listing.insert('end', f'{name}   ({size} байт)')
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
        self.button(top, 'Найти файлы', refresh).pack(side='left')
        qrow = tk.Frame(win, bg=BG)
        qrow.pack(fill='x', padx=12, pady=8)
        tk.Label(qrow, text='Вопрос к ИИ:', bg=BG, fg=FG).pack(side='left')
        question = tk.Entry(qrow, bg=PANEL, fg=FG, insertbackground=FG)
        question.pack(side='left', fill='x', expand=True, padx=8)
        def selected_names():
            return [visible[i][0] for i in listing.curselection()]
        def local_find():
            query = simpledialog.askstring('Поиск в файлах',
                  'Текст для локального поиска (без передачи в интернет):', parent=win)
            if query is None:
                return
            try:
                found = project_context.search_content(root, query)
                body = '\n'.join(f'{name}:{line}: {snippet}' for name, line, snippet in found)
                self.text_window('Локальный поиск — ' + str(len(found)) + ' совпадений',
                                 body or 'Совпадений не найдено')
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
        def send_files():
            if self.busy:
                return
            try:
                selections = project_context.prepare(root, selected_names())
                messages = project_context.build_messages(question.get(), selections)
            except Exception as exc:
                messagebox.showerror('Ошибка', str(exc), parent=win)
                return
            cfg, key = self.settings.copy(), self.api_key
            mode = cfg.get('mode', 'hybrid')
            extra = ('Облако может получить содержимое файлов, если выбран облачный режим или '
                     'разрешён автоматический переход в облако.' if mode != 'local' else
                     'Установлен локальный режим; данные должны остаться на этом компьютере.')
            if not messagebox.askyesno('Подтверждение передачи контекста',
                    'В запрос будет включено содержимое следующих файлов:\n\n' +
                    project_context.report(selections) + '\n\n' + extra +
                    '\n\nОтправить запрос?', parent=win):
                core.audit('project_context', 'denied', 'files=' + str(len(selections)))
                return
            core.audit('project_context', 'approved',
                       'files=' + str(len(selections)) + '; bytes=' + str(sum(x['size'] for x in selections)))
            self.set_busy(True, 'ИИ анализирует выбранные файлы...')
            win.destroy()
            def worker():
                try:
                    result, provider = core.chat(cfg, messages, key)
                    self.events.put(('project_answer', result, provider))
                except Exception as exc:
                    self.events.put(('error', str(exc)))
            threading.Thread(target=worker, daemon=True).start()
        tools = tk.Frame(win, bg=BG)
        tools.pack(fill='x', padx=12, pady=10)
        for label, callback in [('Поиск в содержимом', local_find),
                                ('Отправить выбранные файлы ИИ', send_files)]:
            self.button(tools, label, callback).pack(side='left', padx=5)
        tk.Label(win, bg=BG, fg=FG, text='До 8 текстовых файлов; 32 КиБ каждый, 96 КиБ суммарно.\n'
                 'Содержимое файлов не сохраняется в историю, но ответ ИИ сохраняется.').pack(pady=(0,10))
        refresh()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == '__main__':
    main()
