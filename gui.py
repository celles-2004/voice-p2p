# gui.py - Только клиентский интерфейс
import os
import sys
import json
import threading
import subprocess
import queue
import argparse
import tkinter as tk
import sounddevice as sd
from tkinter import scrolledtext, messagebox, ttk
from client import start_peer

# Если скрипт запущен с аргументом --server, запускаем сервер и выходим
if '--server' in sys.argv:
    # Импортируем server и запускаем его main с нужными аргументами
    import server
    # Извлекаем порт, если он указан
    port = 17789
    try:
        idx = sys.argv.index('--port')
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        pass
    # Подменяем sys.argv для server.main()
    sys.argv = ['server.py', '--port', str(port)]
    server.main()
    sys.exit(0)

class VoiceChatGUI(tk.Tk):
    # Главое окно голосового чата с управлением сервером и клиентом
    def __init__(self):
        super().__init__()
        self.title('Голосовой чат P2P')
        self.geometry('800x700')

        # Файл конфигурации для сохранения настроек
        self.config_file = 'voice_chat_config.json'

        # Состояние сервера
        self.server_process = None
        self.server_log_queue = queue.Queue()
        
        # Состояние клиента
        self.peer_thread = None
        self.peer_stop_event = None
        self.chat_send_q = None

        # Тема (загружаем из конфига при запуске)
        self.dark_mode = self.load_config()
        self.colors = self.get_dark_colors() if self.dark_mode else self.get_light_colors()
        self.configure(bg=self.colors['bg'])

        # Аудио устройства
        try:
            devices = sd.query_devices()
            self.input_devices = {}
            for i, d in enumerate(devices):
                if d.get('max_input_channels', 0) > 0:
                    rate = d.get('default_samplerate', 'N/A')
                    self.input_devices[f"{d['name']} ({rate} Гц)"] = i

            self.output_devices = {}
            for i, d in enumerate(devices):
                if d.get('max_output_channels', 0) > 0:
                    rate = d.get('default_samplerate', 'N/A')
                    self.output_devices[f"{d['name']} ({rate} Гц)"] = i
        except Exception as e:
            messagebox.showerror("Ошибка аудио", str(e))
            self.input_devices = {}
            self.output_devices = {}

        # Создание интерфейса
        self.create_widgets()

        # Применяем тему
        self.apply_theme()

        # Запуск обновление логов сервера
        self.after(100, self.update_server_logs)

        # Сохраняем настройки при закрытии окна
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_config(self):
        """Загрузка конфигурации из файла"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    return config.get('dark_mode', False)
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
        return False

    def save_config(self):
        """Сохранение конфигурации в файл"""
        try:
            config = {
                'dark_mode': self.dark_mode
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")

    def on_closing(self):
        """Обработка закрытия окна"""
        # Останавливаем сервер если запущен
        if self.server_process:
            self.stop_server()

        # Отключаем клиента если подключен
        if self.peer_stop_event:
            self.disconnect_client()

        # Сохраняем конфигурацию
        self.save_config()

        # Закрываем приложение
        self.destroy()

    def get_light_colors(self):
        return {
            'bg': '#f0f0f0',
            'fg': '#000000',
            'text_bg': '#ffffff',
            'text_fg': '#000000',
            'entry_bg': '#ffffff',
            'button_bg': '#e0e0e0',
            'select_bg': '#d0d0d0',
            'frame_bg': '#e8e8e8',
            'label_bg': '#f0f0f0'
        }
        
    def get_dark_colors(self):
        return{
            'bg': '#2d2d30',
            'fg': '#ffffff',
            'text_bg': '#1e1e1e',
            'text_fg': '#d4d4d4',
            'entry_bg': '#3e3e42',
            'button_bg': '#3e3e42',
            'select_bg': '#505050',
            'frame_bg': '#252526',
            'label_bg': '#2d2d30'
        }
    
    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.colors = self.get_dark_colors() if self.dark_mode else self.get_light_colors()
        self.theme_btn.config(text='☀️ Светлая тема' if self.dark_mode else '🌙 Темная тема')
        self.apply_theme()
        self.save_config()

    def apply_theme(self):
        self.configure(bg=self.colors['bg'])
    
        def apply_to_widget(widget):
            try:
                widget_type = widget.winfo_class()
    
                if widget_type in ('Frame', 'TFrame'):
                    widget.configure(bg=self.colors['frame_bg'])
                elif widget_type in ('Text', 'ScrolledText'):
                    widget.configure(bg=self.colors['text_bg'], fg=self.colors['text_fg'])
                elif widget_type == 'Entry':
                    widget.configure(bg=self.colors['entry_bg'], fg=self.colors['fg'])
                elif widget_type == 'Button':
                    widget.configure(bg=self.colors['button_bg'], fg=self.colors['fg'])
                elif widget_type == 'Label':
                    widget.configure(bg=self.colors['label_bg'], fg=self.colors['fg'])
                elif widget_type == 'Labelframe':
                    widget.configure(bg=self.colors['frame_bg'], fg=self.colors['fg'])
            except:
                pass
            
            for child in widget.winfo_children():
                apply_to_widget(child)
    
        apply_to_widget(self)
        
        # Применяем стили для ttk виджетов
        try:
            style = ttk.Style()
            style.theme_use('default')
            
            # Конфигурируем стили для ttk
            style.configure('TNotebook', background=self.colors['frame_bg'])
            style.configure('TNotebook.Tab', background=self.colors['button_bg'], 
                          foreground=self.colors['fg'])
            style.map('TNotebook.Tab', background=[('selected', self.colors['select_bg'])])
        except:
            pass

    def create_widgets(self):
        # Создаем Notebook (вкладки)
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=5, pady=5)

        # Вкладка Сервер
        server_tab = tk.Frame(notebook, bg=self.colors['frame_bg'])
        notebook.add(server_tab, text='📡 Сервер')
        self.create_server_tab(server_tab)

        # Вкладка Клиент
        client_tab = tk.Frame(notebook, bg=self.colors['frame_bg'])
        notebook.add(client_tab, text='🎧 Клиент')
        self.create_client_tab(client_tab)
        
        # Кнопка темы
        self.theme_btn = tk.Button(self, text='☀️ Светлая тема' if self.dark_mode else '🌙 Темная тема', command=self.toggle_theme, bg=self.colors['button_bg'], fg=self.colors['fg'])
        self.theme_btn.pack(side='bottom', pady=5)
    
    def create_server_tab(self, parent):
        # Настройки сервера
        server_frame = tk.LabelFrame(parent, text="Управление сервером", bg=self.colors['frame_bg'], fg=self.colors['fg'])
        server_frame.pack(fill='x', padx=10, pady=10)
        
        # Порт сервера
        tk.Label(server_frame, text="Порт сервера:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=0, sticky='w', padx=5, pady=5)
        
        self.server_port_var = tk.StringVar(value='17789')
        tk.Entry(server_frame, textvariable=self.server_port_var, width=10, bg=self.colors['entry_bg'], fg=self.colors['fg']).grid(row=0, column=1, sticky='w', padx=5, pady=5)
        
        # Кнопки управления сервером
        self.start_server_btn = tk.Button(server_frame, text="▶ Запустить сервер", command=self.start_server, bg=self.colors['button_bg'], fg=self.colors['fg'])
        self.start_server_btn.grid(row=0, column=2, padx=5, pady=5)
        
        self.stop_server_btn = tk.Button(server_frame, text="⏹ Остановить сервер", command=self.stop_server, state='disabled', bg=self.colors['button_bg'], fg=self.colors['fg'])
        self.stop_server_btn.grid(row=0, column=3, padx=5, pady=5)
        
        # Логи сервера
        log_frame = tk.LabelFrame(parent, text="Логи сервера", bg=self.colors['frame_bg'], fg=self.colors['fg'])
        log_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        self.server_log = scrolledtext.ScrolledText(log_frame, height=15, bg=self.colors['text_bg'], fg=self.colors['text_fg'])
        self.server_log.pack(fill='both', expand=True, padx=5, pady=5)
        self.server_log.config(state='disabled')
    
    def create_client_tab(self, parent):
        # Основной контейнер клиента
        main_frame = tk.Frame(parent, bg=self.colors['frame_bg'])
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Настройки подключения
        conn_frame = tk.LabelFrame(main_frame, text="Настройки подключения", bg=self.colors['frame_bg'], fg=self.colors['fg'])
        conn_frame.pack(fill='x', pady=(0, 10))
        
        # Строка 1: Сервер и порт
        tk.Label(conn_frame, text="Сервер:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=0, sticky='w', padx=5, pady=5)
        
        self.server_ip_var = tk.StringVar(value='127.0.0.1')
        tk.Entry(conn_frame, textvariable=self.server_ip_var, width=15, bg=self.colors['entry_bg'], fg=self.colors['fg']).grid(row=0, column=1, sticky='w', padx=5, pady=5)
        
        tk.Label(conn_frame, text="Порт:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=2, sticky='w', padx=5, pady=5)
        
        self.client_port_var = tk.StringVar(value='17789')
        tk.Entry(conn_frame, textvariable=self.client_port_var, width=8, bg=self.colors['entry_bg'], fg=self.colors['fg']).grid(row=0, column=3, sticky='w', padx=5, pady=5)
        
        # Строка 2: Комната и ID
        tk.Label(conn_frame, text="Комната:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=1, column=0, sticky='w', padx=5, pady=5)
        
        self.room_var = tk.StringVar(value='chatroom')
        tk.Entry(conn_frame, textvariable=self.room_var, width=15, bg=self.colors['entry_bg'], fg=self.colors['fg']).grid(row=1, column=1, sticky='w', padx=5, pady=5)
        
        tk.Label(conn_frame, text="Ваш ID:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=1, column=2, sticky='w', padx=5, pady=5)
        
        self.id_var = tk.StringVar(value='user1')
        tk.Entry(conn_frame, textvariable=self.id_var, width=8, bg=self.colors['entry_bg'], fg=self.colors['fg']).grid(row=1, column=3, sticky='w', padx=5, pady=5)
        
        # Аудио устройства
        audio_frame = tk.LabelFrame(main_frame, text="Аудио устройства", bg=self.colors['frame_bg'], fg=self.colors['fg'])
        audio_frame.pack(fill='x', pady=(0, 10))
        
        # Микрофон
        tk.Label(audio_frame, text="Микрофон:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=0, sticky='w', padx=5, pady=5)

        if self.input_devices:
            self.input_var = tk.StringVar(value=list(self.input_devices.keys())[0])
            input_menu = tk.OptionMenu(audio_frame, self.input_var, *self.input_devices.keys())
            input_menu.grid(row=0, column=1, sticky='w', padx=5, pady=5)
            input_menu.configure(bg=self.colors['button_bg'], fg=self.colors['fg'])
            self.mic_indicator = tk.Canvas(audio_frame, width=20, height=20, bg='#00ff00', highlightthickness=0)
            self.mic_indicator.grid(row=0, column=2, padx=(0, 10))
        else:
            self.input_var = tk.StringVar(value='Нет устройств')
            tk.Label(audio_frame, text="Нет микрофонов", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=1, sticky='w', padx=5, pady=5)

        # Динамики
        tk.Label(audio_frame, text="Динамики:", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=3, sticky='w', padx=5, pady=5)

        if self.output_devices:
            self.output_var = tk.StringVar(value=list(self.output_devices.keys())[0])
            output_menu = tk.OptionMenu(audio_frame, self.output_var, *self.output_devices.keys())
            output_menu.grid(row=0, column=4, sticky='w', padx=5, pady=5)
            output_menu.configure(bg=self.colors['button_bg'], fg=self.colors['fg'])
            self.speaker_indicator = tk.Canvas(audio_frame, width=20, height=20, bg='#00ff00', highlightthickness=0)
            self.speaker_indicator.grid(row=0, column=5, padx=(0, 10))

        else:
            self.output_var = tk.StringVar(value='Нет устройств')
            tk.Label(audio_frame, text="Нет динамиков", bg=self.colors['frame_bg'], fg=self.colors['fg']).grid(row=0, column=4, sticky='w', padx=5, pady=5)
        
        # Кнопки управления клиентом
        btn_frame = tk.Frame(main_frame, bg=self.colors['frame_bg'])
        btn_frame.pack(fill='x', pady=(0, 10))
        
        self.connect_btn = tk.Button(btn_frame, text="▶ Подключиться", command=self.connect_client, bg=self.colors['button_bg'], fg=self.colors['fg'])
        self.connect_btn.pack(side='left', padx=5)
        
        self.disconnect_btn = tk.Button(btn_frame, text="⏹ Отключиться", command=self.disconnect_client, state='disabled', bg=self.colors['button_bg'], fg=self.colors['fg'])
        self.disconnect_btn.pack(side='left', padx=5)
        
        # Чат
        chat_frame = tk.LabelFrame(main_frame, text="Чат", bg=self.colors['frame_bg'], fg=self.colors['fg'])
        chat_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        self.chat_text = scrolledtext.ScrolledText(chat_frame, height=10, bg=self.colors['text_bg'], fg=self.colors['text_fg'])
        self.chat_text.pack(fill='both', expand=True, padx=5, pady=5)
        self.chat_text.config(state='disabled')
        
        # Ввод сообщения
        input_frame = tk.Frame(chat_frame, bg=self.colors['frame_bg'])
        input_frame.pack(fill='x', padx=5, pady=(0, 5))
        
        self.message_var = tk.StringVar()
        self.message_entry = tk.Entry(input_frame, textvariable=self.message_var, bg=self.colors['entry_bg'], fg=self.colors['fg'])
        self.message_entry.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.message_entry.bind('<Return>', lambda e: self.send_message())
        
        self.send_btn = tk.Button(input_frame, text="Отправить", command=self.send_message, bg=self.colors['button_bg'], fg=self.colors['fg'])
        self.send_btn.pack(side='right')
        
        # Статус клиента
        self.client_status_var = tk.StringVar(value="Готов к подключению")
        tk.Label(main_frame, textvariable=self.client_status_var, bg=self.colors['frame_bg'], fg=self.colors['fg']).pack()

        

    def start_server(self):
        """Запуск сервера"""
        if self.server_process:
            messagebox.showinfo("Информация", "Сервер уже запущен")
            return

        try:
            port = int(self.server_port_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом")
            return

        # Определяем путь к текущему исполняемому файлу
        if getattr(sys, 'frozen', False):
            # В режиме EXE – сам exe
            exe_path = sys.executable
        else:
            # В режиме разработки – python gui.py
            exe_path = sys.executable
            # Для разработки запускаем gui.py с аргументом --server
            # (но тогда нужно учесть, что gui.py будет запущен снова, что нежелательно)
            # Поэтому лучше в разработке оставить старый способ или тоже использовать эту логику.
            # Упростим: в разработке тоже будем использовать тот же подход
            # (т.е. запускать python gui.py --server ...)
            # Тогда наш код выше с проверкой --server сработает.

        cmd = [exe_path, '--server', '--port', str(port)]
        if not getattr(sys, 'frozen', False):
            # В режиме разработки нужно явно указать gui.py
            cmd = [sys.executable, 'gui.py', '--server', '--port', str(port)]

        # Запускаем сервер как подпроцесс, скрывая окно (Windows)
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW  # или DETACHED_PROCESS

        self.server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            creationflags=creationflags
        )

        # Запускаем поток для чтения вывода сервера
        threading.Thread(target=self.read_server_output, daemon=True).start()

        self.start_server_btn.config(state='disabled')
        self.stop_server_btn.config(state='normal')
        self.append_server_log(f"Сервер запущен на порту {port}\n")


    def stop_server(self):
        """Остановка сервера"""
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except:
                self.server_process.kill()

            self.server_process = None
            self.append_server_log("Сервер остановлен\n")

        self.start_server_btn.config(state='normal')
        self.stop_server_btn.config(state='disabled')

    def read_server_output(self):
        """Чтение вывода сервера"""
        try:
            while self.server_process and self.server_process.poll() is None:
                line = self.server_process.stdout.readline()
                if line:
                    self.server_log_queue.put(line)
                else:
                    break
        except:
            pass

    def update_server_logs(self):
        """Обновление логов сервера в интерфейсе"""
        try:
            while True:
                line = self.server_log_queue.get_nowait()
                self.append_server_log(line)
        except queue.Empty:
            pass

        # Проверяем статус процесса
        if self.server_process and self.server_process.poll() is not None:
            self.append_server_log(f"Сервер завершил работу (код: {self.server_process.returncode})\n")
            self.server_process = None
            self.start_server_btn.config(state='normal')
            self.stop_server_btn.config(state='disabled')

        self.after(100, self.update_server_logs)

    def append_server_log(self, text):
        """Добавление текста в лог сервера"""
        self.server_log.config(state='normal')
        self.server_log.insert('end', text)
        self.server_log.see('end')
        self.server_log.config(state='disabled')

    def connect_client(self):
        """Подключение клиента"""
        if self.peer_thread and self.peer_thread.is_alive():
            messagebox.showinfo("Информация", "Клиент уже подключен")
            return
        
        # Проверка устройств
        input_device = self.input_devices.get(self.input_var.get())
        output_device = self.output_devices.get(self.output_var.get())

        if input_device is None or output_device is None:
            messagebox.showerror("Ошибка", "Выберите аудио устройства")
            return
        
        # Создаем очередь и событие остановки
        self.peer_stop_event = threading.Event()
        self.chat_send_q = queue.Queue()

        # Запуск клиента в отдельном потоке
        try:
            self.peer_thread = start_peer(
                server_url=f"ws://{self.server_ip_var.get()}:{self.client_port_var.get()}/ws",
                room=self.room_var.get(),
                peer_id=self.id_var.get(),
                bind_ip='0.0.0.0',
                bind_port=0,
                input_device=input_device,
                output_device=output_device,
                stop_event=self.peer_stop_event,
                chat_recv_cb=self.on_chat_message,
                chat_send_q=self.chat_send_q,
                mic_rms_cb=self.on_mic_rms,
                speaker_rms_cb=self.on_speaker_rms
            )

            # Обновление интерфейса
            self.connect_btn.config(state='disabled')
            self.disconnect_btn.config(state='normal')
            self.client_status_var.set("Подключено. Ожидание собеседника...")
            self.append_chat("Система: Подключение установлено\n")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось подключиться: {str(e)}")

    def disconnect_client(self):
        """Отключение клиента"""
        if self.peer_stop_event:
            self.peer_stop_event.set()
        
        if hasattr(self, 'mic_indicator'):
            self.mic_indicator.config(bg='#00ff00')
        if hasattr(self, 'speaker_indicator'):
            self.speaker_indicator.config(bg='#00ff00')
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.client_status_var.set("Отключено")
        self.append_chat("Система: Отключено\n")
    
    def send_message(self):
        """Отправка сообщения"""
        message = self.message_var.get().strip()
        if not message:
            return
        
        if self.chat_send_q:
            self.chat_send_q.put(message)
            self.append_chat(f"Вы: {message}\n")
            self.message_var.set("")
        else:
            messagebox.showwarning("Предупреждение", "Сначала подключитесь")


    def on_chat_message(self, sender, text):
        """Обработка новых сообщений"""
        self.append_chat(f"{sender}: {text}\n")

    def append_chat(self, text):
        """Добавление текста в чат"""
        self.chat_text.config(state='normal')
        self.chat_text.insert('end', text)
        self.chat_text.see('end')
        self.chat_text.config(state='disabled')

    def on_mic_rms(self, level):
        """Вызывается из клиента при изменении уровня микрофона"""
        self.after(0, lambda: self.update_mic_indicator(level))

    def on_speaker_rms(self, level):
        """Вызывается из клиента при изменении уровня динамиков"""
        self.after(0, lambda: self.update_speaker_indicator(level))

    def update_mic_indicator(self, level):
        """Обновляет цвет индикатора микрофона"""
        color = self.get_level_color(level)
        self.mic_indicator.config(bg=color)

    def update_speaker_indicator(self, level):
        """Обновляет цвет индикатора динамиков"""
        color = self.get_level_color(level)
        self.speaker_indicator.config(bg=color)

    def get_level_color(self, level):
        """Возвращает цвет в зависимости от уровня (0-100)"""
        if level < 10:
            return '#00ff00'  # зелёный
        elif level < 50:
            return '#ffff00'  # жёлтый
        else:
            return '#ff0000'  # красный

if __name__ == '__main__':
    app = VoiceChatGUI()
    app.mainloop()