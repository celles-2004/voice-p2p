import os
import sys
import threading
import asyncio
import logging
import queue
import tkinter as tk
import sounddevice as sd
from tkinter import scrolledtext, messagebox
from peer import start_peer
import threading

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(SCRIPT_DIR, 'rendezvous_server.py')
import rendezvous_server


class ServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Rendezvous Server GUI')
        self.geometry('700x480')
        
        self.inproc_var = tk.BooleanVar(value=True)

        top_frame = tk.Frame(self)
        top_frame.pack(fill='x', padx=8, pady=6)

        tk.Label(top_frame, text='Port:').pack(side='left')
        self.port_var = tk.StringVar(value='8080')
        tk.Entry(top_frame, textvariable=self.port_var, width=8).pack(side='left', padx=(4, 12))

        # option: run in-process instead of subprocess (enabled by default)
        tk.Checkbutton(top_frame, text='Run in-process', variable=self.inproc_var).pack(side='left', padx=(6,0))

        self.start_btn = tk.Button(top_frame, text='Start Server', command=self.start_server)
        self.start_btn.pack(side='left')
        self.stop_btn = tk.Button(top_frame, text='Stop Server', command=self.stop_server, state='disabled')
        self.stop_btn.pack(side='left', padx=(6,0))

        self.status_var = tk.StringVar(value='Stopped')
        tk.Label(top_frame, textvariable=self.status_var).pack(side='right')

        self.log_box = scrolledtext.ScrolledText(self, state='disabled', wrap='word')
        self.log_box.pack(fill='both', expand=True, padx=8, pady=(0,8))

        self.proc = None
        self.log_queue = queue.Queue()
        self.log_thread = None

        # in-process server state
        self.server_thread = None
        self.server_loop = None
        self.server_runner = None
        self.log_handler = None

        # Client controls frame
        client_frame = tk.Frame(self)
        client_frame.pack(fill='x', padx=8, pady=(4,6))

        # Audio devices
        try:
            self.sd_devices = sd.query_devices()
        except Exception as e:
            self.sd_devices = []
            messagebox.showerror("Audio error", str(e))

        # maps: name -> index
        self.input_dev_map = {
            d['name']: i
            for i, d in enumerate(self.sd_devices)
            if d.get('max_input_channels', 0) > 0
        }

        self.output_dev_map = {
            d['name']: i
            for i, d in enumerate(self.sd_devices)
            if d.get('max_output_channels', 0) > 0
        }

        self.client_process = None


        # UI
        tk.Label(client_frame, text='Server IP:').grid(row=0, column=0, sticky='w')
        self.client_server_ip_var = tk.StringVar(value='127.0.0.1')
        tk.Entry(client_frame, textvariable=self.client_server_ip_var, width=16).grid(row=0, column=1, sticky='w', padx=(4,6))
        tk.Label(client_frame, text='Port:').grid(row=0, column=2, sticky='w')
        self.client_server_port_var = tk.StringVar(value='8080')
        tk.Entry(client_frame, textvariable=self.client_server_port_var, width=8).grid(row=0, column=3, sticky='w')
        tk.Label(client_frame, text='Room:').grid(row=1, column=0, sticky='w')
        self.client_room_var = tk.StringVar(value='testroom')
        tk.Entry(client_frame, textvariable=self.client_room_var, width=12).grid(row=1, column=1, sticky='w')
        tk.Label(client_frame, text='ID:').grid(row=1, column=2, sticky='w')
        self.client_id_var = tk.StringVar(value='peer1')
        tk.Entry(client_frame, textvariable=self.client_id_var, width=12).grid(row=1, column=3, sticky='w')

        # Mic selection
        tk.Label(client_frame, text='Mic:').grid(row=2, column=0, sticky='w')

        self.input_dev_var = tk.StringVar(
            value=next(iter(self.input_dev_map)) if self.input_dev_map else ''
        )

        tk.OptionMenu(
            client_frame,
            self.input_dev_var,
            *self.input_dev_map.keys()
        ).grid(row=2, column=1, sticky='w')

        # Speaker selection
        tk.Label(client_frame, text='Speaker:').grid(row=2, column=2, sticky='w')
        
        self.output_dev_var = tk.StringVar(
            value=next(iter(self.output_dev_map)) if self.output_dev_map else ''
        )
        
        tk.OptionMenu(
            client_frame,
            self.output_dev_var,
            *self.output_dev_map.keys()
        ).grid(row=2, column=3, sticky='w')

        # Start client button
        self.start_client_btn = tk.Button(
            client_frame,
            text='Start Client',
            command=self.start_peer_process
        )
        self.start_client_btn.grid(row=3, column=3, sticky='e', pady=(6, 0))

        # Stop client button
        self.stop_client_btn = tk.Button(
            client_frame,
            text='Stop Client',
            command=self.stop_peer_process,
            state='disabled'
        )
        self.stop_client_btn.grid(row=3, column=2, sticky='e', pady=(6, 0))

        # Advanced options (bind IP/port) - hidden by default
        self.show_advanced_var = tk.BooleanVar(value=False)
        tk.Checkbutton(client_frame, text='Show advanced', variable=self.show_advanced_var, command=lambda: self._toggle_advanced(adv_frame)).grid(row=0, column=4, padx=(8,0))

        # move bind IP/port into adv_frame so it can be hidden
        adv_frame = tk.Frame(client_frame)
        adv_frame.grid(row=2, column=0, columnspan=4, sticky='w')
        tk.Label(adv_frame, text='Bind IP:').grid(row=0, column=0, sticky='w')
        self.client_bind_ip_var = tk.StringVar(value='0.0.0.0')
        tk.Entry(adv_frame, textvariable=self.client_bind_ip_var, width=12).grid(row=0, column=1, sticky='w')

        tk.Label(adv_frame, text='Bind Port:').grid(row=0, column=2, sticky='w')
        self.client_bind_port_var = tk.StringVar(value='0')
        tk.Entry(adv_frame, textvariable=self.client_bind_port_var, width=12).grid(row=0, column=3, sticky='w')

        # hide advanced by default
        adv_frame.grid_remove()

        self.after(200, self._poll_log_queue)

        # Auto-size window to fit content (avoid needing manual stretching)
        # Use the original geometry as a minimum baseline
        try:
            self.update_idletasks()
            req_w = self.winfo_reqwidth() + 24
            req_h = self.winfo_reqheight() + 24
            base_w, base_h = 700, 480
            w = max(base_w, req_w)
            h = max(base_h, req_h)
            # limit to reasonable maximums to avoid too large windows
            w = min(w, 1400)
            h = min(h, 1000)
            self.geometry(f"{w}x{h}")
            self.minsize(min(w, 600), min(h, 400))
        except Exception:
            pass

    def start_server(self):
        if self.proc or self.server_thread:
            messagebox.showinfo('Info', 'Server already running')
            return
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror('Error', 'Port must be an integer')
            return
        if self.inproc_var.get():
            # start in-process server in background thread with its own event loop
            self.server_thread = threading.Thread(target=self._server_thread, args=(port,), daemon=True)
            self.server_thread.start()
            self.status_var.set(f'Running (in-process) on port {port}')
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')
            self._append_log(f'Started in-process server on port {port}\n')
        else:
            cmd = [sys.executable, SERVER_SCRIPT, '--port', str(port)]
            # start subprocess and capture stdout/stderr
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=SCRIPT_DIR)
            self.status_var.set(f'Running on port {port}')
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')

            # start reader thread
            self.log_thread = threading.Thread(target=self._reader_thread, daemon=True)
            self.log_thread.start()
            self._append_log(f'Launched server: {" ".join(cmd)}\n')

    def stop_server(self):
        # stop subprocess server
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None
            self.status_var.set('Stopped')
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')
            self._append_log('Server stopped (subprocess)\n')
            return

        # stop in-process server
        if self.server_thread and self.server_loop:
            try:
                # schedule cleanup
                fut = asyncio.run_coroutine_threadsafe(rendezvous_server.stop_server_runner(self.server_runner), self.server_loop)
                fut.result(timeout=5)
            except Exception:
                pass
            try:
                self.server_loop.call_soon_threadsafe(self.server_loop.stop)
            except Exception:
                pass
            # wait for thread to finish
            self.server_thread.join(timeout=2)
            self.server_thread = None
            self.server_loop = None
            self.server_runner = None
            # remove logging handler if added
            if self.log_handler:
                logging.getLogger().removeHandler(self.log_handler)
                self.log_handler = None
            self.status_var.set('Stopped')
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')
            self._append_log('Server stopped (in-process)\n')
            return

    def _reader_thread(self):
        proc = self.proc
        try:
            for line in proc.stdout:
                self.log_queue.put(line)
        except Exception:
            pass

    def _server_thread(self, port: int):
        # runs in background thread
        loop = asyncio.new_event_loop()
        self.server_loop = loop
        asyncio.set_event_loop(loop)
        try:
            runner = loop.run_until_complete(rendezvous_server.create_server_runner(port))
            self.server_runner = runner
            # add logging handler to forward logs to GUI
            class QueueHandler(logging.Handler):
                def __init__(self, q):
                    super().__init__()
                    self.q = q
                def emit(self, record):
                    try:
                        msg = self.format(record)
                        self.q.put(msg + "\n")
                    except Exception:
                        pass

            h = QueueHandler(self.log_queue)
            h.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            logging.getLogger().addHandler(h)
            self.log_handler = h

            # run loop until stopped
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(runner.cleanup())
            except Exception:
                pass
            try:
                logging.getLogger().removeHandler(self.log_handler)
            except Exception:
                pass
            loop.close()

    def _toggle_advanced(self, adv_frame):
        try:
            if self.show_advanced_var.get():
                adv_frame.grid()
            else:
                adv_frame.grid_remove()
        except Exception:
            pass
    
    def start_peer_process(self):
        self.peer_stop_event = threading.Event()
    
        server_ip = self.client_server_ip_var.get().strip()
        server_port = self.client_server_port_var.get().strip()
    
        self.peer_thread = threading.Thread(
            target=start_peer,
            daemon=True,
            args=(
                f"ws://{server_ip}:{server_port}/ws",
                self.client_room_var.get(),
                self.client_id_var.get(),
                self.client_bind_ip_var.get(),
                self.client_bind_port_var.get(),
                self.input_dev_map.get(self.input_dev_var.get()),
                self.output_dev_map.get(self.output_dev_var.get()),
                self.peer_stop_event
            )
        )
        self.peer_thread.start()
    
        self.start_client_btn.config(state='disabled')
        self.stop_client_btn.config(state='normal')


    
    def stop_peer_process(self):
        if self.peer_stop_event:
            self.peer_stop_event.set()
    
        self.start_client_btn.config(state='normal')
        self.stop_client_btn.config(state='disabled')
    

    def _poll_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        # if process finished, update state
        if self.proc and self.proc.poll() is not None:
            self._append_log(f'Process exited with code {self.proc.returncode}\n')
            self.proc = None
            self.status_var.set('Stopped')
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')
        self.after(200, self._poll_log_queue)

    def _append_log(self, text):
        self.log_box.config(state='normal')
        self.log_box.insert('end', text)
        self.log_box.see('end')
        self.log_box.config(state='disabled')

if __name__ == '__main__':
    app = ServerGUI()
    app.mainloop()
