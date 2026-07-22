import os
import sys
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# Try importing TkinterDnD for native drag-and-drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# Flag to prevent background sub-processes from opening black CMD windows on Windows
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

# Supported File Extensions
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v', '.ts', '.m2ts', '.vob', '.3gp'}
AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus', '.alac', '.aiff'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif', '.gif'}

FILE_TYPES = [
    ("All Supported Media", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.mp3 *.wav *.flac *.aac *.ogg *.m4a *.png *.jpg *.jpeg *.webp *.bmp *.gif"),
    ("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v *.ts"),
    ("Audio Files", "*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.opus"),
    ("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff"),
    ("All Files", "*.*")
]

def get_ffmpeg_path() -> str:
    """Finds bundled ffmpeg.exe (PyInstaller/Nuitka) or checks next to .exe or system PATH."""
    if hasattr(sys, '_MEIPASS'):
        bundled = os.path.join(sys._MEIPASS, 'ffmpeg.exe')
        if os.path.exists(bundled):
            return bundled
    
    local_ffmpeg = Path(sys.argv[0]).parent / "ffmpeg.exe"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
        
    return "ffmpeg"

def auto_detect_gpu() -> str:
    """Detects available GPU vendor on Windows using PowerShell/WMI without popping up a CMD window."""
    try:
        cmd = ["powershell", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
        output = subprocess.check_output(
            cmd, 
            text=True, 
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        ).lower()
        
        if "nvidia" in output or "geforce" in output or "quadro" in output:
            return "NVIDIA (NVENC)"
        elif "amd" in output or "radeon" in output:
            return "AMD (AMF)"
        elif "intel" in output or "arc" in output or "iris" in output:
            return "Intel (QSV)"
    except Exception:
        pass
    return "CPU Only (Software)"

class UniversalConverterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal Media Converter")
        self.root.geometry("640x450")
        self.root.resizable(False, False)

        self.selected_files = []
        self.show_advanced = tk.BooleanVar(value=False)

        # UI Styling
        self.style = ttk.Style()
        self.style.theme_use('vista' if 'vista' in self.style.theme_names() else 'default')
        self.style.configure(".", font=("Segoe UI", 9))

        self.create_widgets()
        self.detect_hardware()

    def create_widgets(self):
        # --- 1. File Selection Area (Clickable Dropzone) ---
        file_frame = ttk.LabelFrame(self.root, text=" 1. Files to Convert ", padding=10)
        file_frame.pack(fill="x", padx=15, pady=(10, 5))

        list_container = ttk.Frame(file_frame)
        list_container.pack(fill="both", expand=True)

        self.file_listbox = tk.Listbox(
            list_container, 
            height=4, 
            selectmode=tk.EXTENDED, 
            relief="solid", 
            bd=1,
            font=("Segoe UI", 9),
            cursor="hand2"
        )
        self.file_listbox.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        # Click listbox area to open file browser
        self.file_listbox.bind("<Button-1>", self.on_listbox_click)

        # Configure Drag & Drop on the listbox if library is available
        if DND_AVAILABLE:
            self.file_listbox.drop_target_register(DND_FILES)
            self.file_listbox.dnd_bind('<<Drop>>', self.on_file_drop)
            placeholder = " 📥 Drag & Drop files here, or click to browse"
        else:
            placeholder = " 📁 Click here or press 'Add Files...' to select media files"

        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.file_listbox.yview)
        scrollbar.pack(side="left", fill="y", padx=(0, 10))
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        self.file_listbox.insert(tk.END, placeholder)

        btn_box = ttk.Frame(list_container)
        btn_box.pack(side="right", fill="y")

        ttk.Button(btn_box, text="Add Files...", command=self.browse_files).pack(fill="x", pady=2)
        ttk.Button(btn_box, text="Clear", command=self.clear_files).pack(fill="x", pady=2)

        # --- 2. Conversion Settings Frame ---
        settings_frame = ttk.LabelFrame(self.root, text=" 2. Output Settings ", padding=10)
        settings_frame.pack(fill="x", padx=15, pady=5)

        # Category Dropdown
        ttk.Label(settings_frame, text="Media Type:").grid(row=0, column=0, sticky="w", pady=4)
        self.category_var = tk.StringVar(value="Video")
        cat_cb = ttk.Combobox(settings_frame, textvariable=self.category_var, state="readonly", width=32)
        cat_cb['values'] = ("Video", "Audio", "Image")
        cat_cb.grid(row=0, column=1, sticky="w", padx=10, pady=4)
        cat_cb.bind("<<ComboboxSelected>>", self.update_format_options)

        # Format Dropdown
        ttk.Label(settings_frame, text="Target Format:").grid(row=1, column=0, sticky="w", pady=4)
        self.format_var = tk.StringVar()
        self.format_cb = ttk.Combobox(settings_frame, textvariable=self.format_var, state="readonly", width=32)
        self.format_cb.grid(row=1, column=1, sticky="w", padx=10, pady=4)

        # Hardware Acceleration Selection
        ttk.Label(settings_frame, text="GPU Hardware:").grid(row=2, column=0, sticky="w", pady=4)
        self.gpu_var = tk.StringVar(value="Detecting...")
        self.gpu_cb = ttk.Combobox(settings_frame, textvariable=self.gpu_var, state="readonly", width=32)
        self.gpu_cb['values'] = ("NVIDIA (NVENC)", "AMD (AMF)", "Intel (QSV)", "CPU Only (Software)")
        self.gpu_cb.grid(row=2, column=1, sticky="w", padx=10, pady=4)

        self.update_format_options()

        # --- 3. Progress Section ---
        progress_frame = ttk.LabelFrame(self.root, text=" 3. Status & Progress ", padding=10)
        progress_frame.pack(fill="x", padx=15, pady=5)

        self.status_label = ttk.Label(progress_frame, text="Ready", font=("Segoe UI", 9, "bold"))
        self.status_label.pack(anchor="w", pady=(0, 4))

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=2)

        # Advanced Logs Toggle
        adv_box = ttk.Frame(progress_frame)
        adv_box.pack(fill="x", pady=(5, 0))

        self.adv_btn = ttk.Checkbutton(
            adv_box, 
            text="🔍 Show Advanced Logs", 
            variable=self.show_advanced, 
            command=self.toggle_advanced_log
        )
        self.adv_btn.pack(side="left")

        # Collapsible Log Frame
        self.log_frame = ttk.LabelFrame(self.root, text=" Detailed Console Log ", padding=8)
        self.log_text = tk.Text(
            self.log_frame, 
            height=8, 
            wrap="word", 
            bg="#1e1e1e", 
            fg="#00ff00", 
            font=("Consolas", 8),
            state="disabled"
        )
        self.log_text.pack(fill="both", expand=True)

        # Action Button
        self.start_btn = ttk.Button(self.root, text="⚡ Start Conversion", command=self.start_conversion_thread)
        self.start_btn.pack(pady=10, ipadx=20, ipady=4)

    def detect_hardware(self):
        detected = auto_detect_gpu()
        self.gpu_var.set(detected)
        self.log(f"System Check: Detected Hardware Acceleration -> {detected}")
        if DND_AVAILABLE:
            self.log("UI Check: Native Drag & Drop enabled")

    def on_listbox_click(self, event):
        if not self.selected_files:
            self.browse_files()

    def on_file_drop(self, event):
        """Handles drag and drop files from Windows File Explorer."""
        dropped_files = self.root.tk.splitlist(event.data)
        self.add_files(dropped_files)

    def toggle_advanced_log(self):
        if self.show_advanced.get():
            self.log_frame.pack(fill="both", expand=True, padx=15, pady=(0, 5))
            self.root.geometry("640x630")
        else:
            self.log_frame.pack_forget()
            self.root.geometry("640x450")

    def update_format_options(self, event=None):
        category = self.category_var.get()
        if category == "Video":
            formats = ("HEVC (H.265) [.mp4]", "AVC (H.264) [.mp4]", "WebM (VP9) [.webm]", "Animated GIF [.gif]")
            self.gpu_cb.config(state="readonly")
        elif category == "Audio":
            formats = ("MP3 [.mp3]", "AAC [.m4a]", "WAV [.wav]", "FLAC [.flac]", "OGG [.ogg]")
            self.gpu_cb.config(state="disabled")
        else:  # Image
            formats = ("PNG [.png]", "JPEG [.jpg]", "WEBP [.webp]", "GIF [.gif]", "BMP [.bmp]")
            self.gpu_cb.config(state="disabled")

        self.format_cb['values'] = formats
        self.format_var.set(formats[0])

    def log(self, text: str):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def add_files(self, file_paths):
        """Helper to append files and auto-detect category."""
        if file_paths:
            if not self.selected_files:
                self.file_listbox.delete(0, tk.END)

            for f in file_paths:
                p = Path(f)
                if p.is_file() and str(p) not in self.selected_files:
                    self.selected_files.append(str(p))
                    self.file_listbox.insert(tk.END, f"  {p.name}")

            if self.selected_files:
                first_ext = Path(self.selected_files[0]).suffix.lower()
                if first_ext in AUDIO_EXTS:
                    self.category_var.set("Audio")
                elif first_ext in IMAGE_EXTS:
                    self.category_var.set("Image")
                elif first_ext in VIDEO_EXTS:
                    self.category_var.set("Video")
                self.update_format_options()

    def browse_files(self):
        files = filedialog.askopenfilenames(title="Select Media Files", filetypes=FILE_TYPES)
        self.add_files(files)

    def clear_files(self):
        self.selected_files.clear()
        self.file_listbox.delete(0, tk.END)
        placeholder = " 📥 Drag & Drop files here, or click to browse" if DND_AVAILABLE else " 📁 Click here or press 'Add Files...' to select media files"
        self.file_listbox.insert(tk.END, placeholder)
        self.status_label.config(text="Ready")
        self.progress_var.set(0.0)

    def get_video_encoder(self, is_hevc: bool, hw_type: str) -> tuple[list, str, str]:
        if "NVIDIA" in hw_type:
            encoder = "hevc_nvenc" if is_hevc else "h264_nvenc"
            return ([encoder, "-preset", "p2"], "-cq", "28" if is_hevc else "23")
        elif "AMD" in hw_type:
            encoder = "hevc_amf" if is_hevc else "h264_amf"
            return ([encoder, "-quality", "speed"], "-rc", "cqp")
        elif "Intel" in hw_type:
            encoder = "hevc_qsv" if is_hevc else "h264_qsv"
            return ([encoder, "-preset", "veryfast"], "-global_quality", "28" if is_hevc else "23")
        else:
            encoder = "libx265" if is_hevc else "libx264"
            return ([encoder, "-preset", "ultrafast"], "-crf", "28" if is_hevc else "23")

    def run_ffmpeg_command(self, cmd: list, base_pct: float, file_weight: float):
        """Runs FFmpeg silently in the background while animating progress."""
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            creationflags=CREATE_NO_WINDOW  # Prevents black CMD window popping up
        )
        
        stderr_lines = []
        def read_stderr():
            for line in process.stderr:
                stderr_lines.append(line)

        reader_thread = threading.Thread(target=read_stderr, daemon=True)
        reader_thread.start()

        simulated_file_pct = 0.0

        while process.poll() is None:
            time.sleep(0.1)
            simulated_file_pct += (95.0 - simulated_file_pct) * 0.02
            current_total = base_pct + (simulated_file_pct / 100.0) * file_weight
            self.progress_var.set(current_total)

        reader_thread.join()
        stderr_text = "".join(stderr_lines)

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, output="", stderr=stderr_text)

        self.progress_var.set(base_pct + file_weight)

    def start_conversion_thread(self):
        if not self.selected_files:
            messagebox.showwarning("No Files", "Please add at least one file to convert.")
            return

        self.start_btn.config(state="disabled")
        self.progress_var.set(0.0)
        threading.Thread(target=self.run_conversion, daemon=True).start()

    def run_conversion(self):
        ffmpeg = get_ffmpeg_path()
        category = self.category_var.get()
        target_fmt = self.format_var.get()
        total_files = len(self.selected_files)

        self.log("=" * 50)
        self.log(f"Batch Start: {total_files} {category} file(s)")

        for index, filepath in enumerate(list(self.selected_files), start=1):
            input_file = Path(filepath)
            
            self.status_label.config(text=f"Converting ({index}/{total_files}): {input_file.name}")
            self.log(f"\n[{index}/{total_files}] Processing: {input_file.name}")

            base_pct = ((index - 1) / total_files) * 100.0
            file_weight = 100.0 / total_files

            # --- VIDEO CONVERSION ---
            if category == "Video":
                gpu_type = self.gpu_var.get()
                
                hw_decode = []
                if "NVIDIA" in gpu_type:
                    hw_decode = ["-hwaccel", "cuda"]
                elif "Intel" in gpu_type:
                    hw_decode = ["-hwaccel", "qsv"]
                elif "AMD" in gpu_type:
                    hw_decode = ["-hwaccel", "dxva2"]

                if "GIF" in target_fmt:
                    out_ext = ".gif"
                    output_file = input_file.parent / f"{input_file.stem}_converted{out_ext}"
                    cmd = [ffmpeg, "-y"] + hw_decode + ["-i", str(input_file), "-vf", "fps=12,scale=480:-1:flags=lanczos", str(output_file)]
                elif "WebM" in target_fmt:
                    out_ext = ".webm"
                    output_file = input_file.parent / f"{input_file.stem}_converted{out_ext}"
                    cmd = [ffmpeg, "-y"] + hw_decode + ["-i", str(input_file), "-c:v", "libvpx-vp9", "-c:a", "libopus", str(output_file)]
                else:
                    is_hevc = "HEVC" in target_fmt
                    out_ext = ".mp4"
                    output_file = input_file.parent / f"{input_file.stem}_converted{out_ext}"
                    
                    encoder_args, q_flag, q_val = self.get_video_encoder(is_hevc, gpu_type)
                    cmd = [ffmpeg, "-y"] + hw_decode + ["-i", str(input_file), "-c:v"] + encoder_args + [q_flag, q_val, "-c:a", "aac", "-b:a", "192k", str(output_file)]

            # --- AUDIO CONVERSION ---
            elif category == "Audio":
                out_ext = target_fmt.split("[")[1].replace("]", "").strip()
                output_file = input_file.parent / f"{input_file.stem}_converted{out_ext}"
                
                codec_args = []
                if ".mp3" in out_ext: codec_args = ["-c:a", "libmp3lame", "-qscale:a", "2"]
                elif ".m4a" in out_ext: codec_args = ["-c:a", "aac", "-b:a", "192k"]
                elif ".wav" in out_ext: codec_args = ["-c:a", "pcm_s16le"]
                elif ".flac" in out_ext: codec_args = ["-c:a", "flac"]
                elif ".ogg" in out_ext: codec_args = ["-c:a", "libvorbis", "-qscale:a", "5"]

                cmd = [ffmpeg, "-y", "-i", str(input_file)] + codec_args + [str(output_file)]

            # --- IMAGE CONVERSION ---
            else:
                out_ext = target_fmt.split("[")[1].replace("]", "").strip()
                output_file = input_file.parent / f"{input_file.stem}_converted{out_ext}"
                cmd = [ffmpeg, "-y", "-i", str(input_file), str(output_file)]

            try:
                self.run_ffmpeg_command(cmd, base_pct, file_weight)
                self.log(f"SUCCESS -> Saved to {output_file.name}")
            except subprocess.CalledProcessError as e:
                self.log(f"ERROR: Failed converting {input_file.name}\n{e.stderr if hasattr(e, 'stderr') else e}")

        self.status_label.config(text="✅ All Conversions Complete!")
        self.log("\nBatch completed successfully!")
        self.start_btn.config(state="normal")
        messagebox.showinfo("Done", "All file conversions are complete!")

if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
        
    app = UniversalConverterGUI(root)
    root.mainloop()