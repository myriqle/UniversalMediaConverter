import os
import sys
import re
import shutil
import subprocess
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
import customtkinter as ctk
from tkinter import filedialog
from tkinterdnd2 import TkinterDnD, DND_FILES

# Appearance & Theme Configuration
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Hide console window when spawning subprocesses on Windows
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# BUNDLED BINARY RESOLUTION
#
# The app ships ffmpeg / ffmpeg.exe and yt-dlp / yt-dlp.exe next to the
# executable (see the build/README notes). We look for those first so end
# users never have to install anything themselves. If they're missing
# (e.g. running from source during development) we fall back to PATH.

def get_app_dir():
    """Directory the running exe lives in (or the script dir when not frozen)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _find_bundled(name):
    exe_name = f"{name}.exe" if sys.platform == "win32" else name
    candidate = os.path.join(get_app_dir(), exe_name)
    if os.path.isfile(candidate):
        return candidate
    return shutil.which(name)


def get_ffmpeg_path():
    return _find_bundled("ffmpeg")


def get_ffprobe_path():
    return _find_bundled("ffprobe")


def get_ytdlp_path():
    return _find_bundled("yt-dlp")


def get_icon_path():
    candidate = os.path.join(get_app_dir(), "icon.ico")
    return candidate if os.path.isfile(candidate) else None


FFMPEG_PATH = get_ffmpeg_path()
FFPROBE_PATH = get_ffprobe_path()
YTDLP_PATH = get_ytdlp_path()
HAS_YTDLP = YTDLP_PATH is not None

# EXTENSION SETS & DIALOG FILTERS
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v', '.ts', '.m2ts', '.vob', '.3gp'}
AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus', '.alac', '.aiff'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif', '.gif'}

SUPPORTED_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS

FILE_TYPES = [
    ("All Supported Media", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.mp3 *.wav *.flac *.aac *.ogg *.m4a *.png *.jpg *.jpeg *.webp *.bmp *.gif"),
    ("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v *.ts *.m2ts *.vob *.3gp"),
    ("Audio Files", "*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma *.opus *.alac *.aiff"),
    ("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff *.tif"),
    ("All Files", "*.*")
]

CATEGORY_MAP = {
    "Video": ["MP4", "MKV", "MOV", "AVI", "WEBM", "FLV", "WMV", "M4V", "TS", "M2TS", "VOB", "3GP"],
    "Audio": ["MP3", "WAV", "FLAC", "AAC", "OGG", "M4A", "WMA", "OPUS", "ALAC", "AIFF"],
    "Image": ["PNG", "JPG", "WEBP", "BMP", "TIFF", "GIF"]
}

AUDIO_TARGET_KEYS = {ext.replace('.', '') for ext in AUDIO_EXTS}
STATIC_IMAGE_KEYS = {ext.replace('.', '') for ext in IMAGE_EXTS} - {'gif'}
VIDEO_TARGET_KEYS = {ext.replace('.', '') for ext in VIDEO_EXTS}


# PRE-FLIGHT CHECK & HARDWARE PROBING

def check_ffmpeg_installed():
    global FFMPEG_PATH, FFPROBE_PATH
    FFMPEG_PATH = get_ffmpeg_path()
    FFPROBE_PATH = get_ffprobe_path()
    return FFMPEG_PATH is not None


def test_encoder(encoder_name):
    try:
        cmd = [
            FFMPEG_PATH, "-y", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=1",
            "-c:v", encoder_name, "-frames:v", "1", "-f", "null", "-"
        ]
        process = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="ignore"
        )
        return process.returncode == 0
    except Exception:
        return False


def detect_gpu_vendors():
    """
    Best-effort detection of installed GPU vendor(s) via Windows WMI, e.g. {'nvidia'},
    {'nvidia', 'intel'}, {'amd'}, etc. Returns an empty set if detection isn't possible
    (non-Windows, WMI unavailable, etc.) so callers can fall back gracefully.
    """
    vendors = set()
    if sys.platform != "win32":
        return vendors
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="ignore", timeout=5
        )
        output = (result.stdout or "").lower()
        if "nvidia" in output:
            vendors.add("nvidia")
        if "amd" in output or "radeon" in output:
            vendors.add("amd")
        if "intel" in output:
            vendors.add("intel")
    except Exception:
        pass
    return vendors


def detect_gpu_encoder():
    vendors = detect_gpu_vendors()

    # Only test the encoder(s) for vendors we've actually confirmed are present.
    # This avoids FFmpeg's h264_amf encoder occasionally reporting a false-positive
    # success on a trivial 1-frame test even on machines with no AMD GPU at all,
    # which was previously causing NVENC/QSV machines to be misreported as AMF.
    candidates = []
    if "nvidia" in vendors:
        candidates.append(("nvenc", "h264_nvenc"))
    if "amd" in vendors:
        candidates.append(("amf", "h264_amf"))
    if "intel" in vendors:
        candidates.append(("qsv", "h264_qsv"))

    # If vendor detection failed outright (non-Windows, WMI blocked, etc.), fall back
    # to testing every encoder, but with NVENC checked first since it's the most
    # common discrete GPU and the least prone to this false-positive behavior.
    if not candidates:
        candidates = [("nvenc", "h264_nvenc"), ("amf", "h264_amf"), ("qsv", "h264_qsv")]

    for label, encoder_name in candidates:
        if test_encoder(encoder_name):
            return label

    return "cpu"


# APPLICATION CLASS

class ModernConverterApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)

        # Window Configuration
        self.title("Universal Media Converter v1.4.0 (with Downloader)")
        self.geometry("920x720")
        self.minsize(820, 620)

        icon_path = get_icon_path()
        if icon_path and sys.platform == "win32":
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Pre-flight Check
        self.ffmpeg_available = check_ffmpeg_installed()
        self.gpu_type = detect_gpu_encoder() if self.ffmpeg_available else "cpu"

        # State & Process Tracking (Converter)
        self.file_queue = []
        self.active_processes = []
        self.is_processing = False
        self.cancel_requested = False
        self.completed_count = 0
        self.queue_lock = threading.Lock()
        self.custom_output_dir = ""

        # State Tracking (Downloader)
        self.dl_custom_output_dir = ""

        self._build_ui()
        self._setup_dnd()
        self._setup_shortcuts()

        if not self.ffmpeg_available:
            self.after(200, self._show_ffmpeg_warning)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # Makes the TabView expand

        # HEADER
        self.header_frame = ctk.CTkFrame(self, corner_radius=10)
        self.header_frame.grid(row=0, column=0, padx=15, pady=(15, 10), sticky="ew")

        self.title_label = ctk.CTkLabel(
            self.header_frame, 
            text="🎬 Universal Media Toolkit", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.pack(side="left", padx=15, pady=12)

        if not self.ffmpeg_available:
            gpu_status_text = "⚠️ FFmpeg Missing!"
            gpu_color = "#EF5350"
        else:
            gpu_status_text = f"Hardware Engine: {self.gpu_type.upper()}" if self.gpu_type != "cpu" else "Engine: CPU (Software Fallback)"
            gpu_color = "#66BB6A" if self.gpu_type != "cpu" else "#FFA000"

        self.subtitle_label = ctk.CTkLabel(
            self.header_frame, 
            text=gpu_status_text, 
            font=ctk.CTkFont(size=12),
            text_color=gpu_color
        )
        self.subtitle_label.pack(side="right", padx=15, pady=12)

        # TABS
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="nsew")

        self.tab_converter = self.tabview.add("🔄 Converter")
        self.tab_downloader = self.tabview.add("⬇️ YouTube Downloader")

        # ==========================================
        # TAB 1: CONVERTER (100% Original Logic)
        # ==========================================
        self.tab_converter.grid_columnconfigure(0, weight=1)
        self.tab_converter.grid_rowconfigure(0, weight=1) # Queue expands

        # QUEUE LIST
        self.queue_frame = ctk.CTkScrollableFrame(self.tab_converter, label_text="Conversion Queue (Drop files or press Ctrl+O)")
        self.queue_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.empty_label = ctk.CTkLabel(
            self.queue_frame,
            text="📥 Drag & Drop Media Files Here to Begin",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="gray"
        )
        self.empty_label.pack(pady=100)

        # DESTINATION SELECTOR 
        self.dest_frame = ctk.CTkFrame(self.tab_converter, corner_radius=10)
        self.dest_frame.grid(row=1, column=0, padx=5, pady=(5, 5), sticky="ew")

        self.dest_label = ctk.CTkLabel(self.dest_frame, text="Output Path:", font=ctk.CTkFont(weight="bold"))
        self.dest_label.pack(side="left", padx=(15, 5), pady=8)

        self.dest_entry = ctk.CTkEntry(self.dest_frame, placeholder_text="Same as Source Directory", width=400)
        self.dest_entry.pack(side="left", padx=5, pady=8, fill="x", expand=True)
        self.dest_entry.configure(state="disabled")

        self.browse_btn = ctk.CTkButton(
            self.dest_frame, text="Browse...", width=90, command=self._browse_output_folder
        )
        self.browse_btn.pack(side="left", padx=5, pady=8)

        self.reset_dest_btn = ctk.CTkButton(
            self.dest_frame, text="Reset", width=60, fg_color="#555555", hover_color="#333333", command=self._reset_output_folder
        )
        self.reset_dest_btn.pack(side="left", padx=(5, 15), pady=8)

        # CONTROLS
        self.controls_frame = ctk.CTkFrame(self.tab_converter, corner_radius=10)
        self.controls_frame.grid(row=2, column=0, padx=5, pady=10, sticky="ew")

        # Category Filter Dropdown
        self.cat_label = ctk.CTkLabel(self.controls_frame, text="Category:", font=ctk.CTkFont(weight="bold"))
        self.cat_label.pack(side="left", padx=(15, 5), pady=12)

        self.cat_dropdown = ctk.CTkOptionMenu(
            self.controls_frame, 
            values=list(CATEGORY_MAP.keys()),
            command=self._on_category_change,
            width=100
        )
        self.cat_dropdown.pack(side="left", padx=5, pady=12)

        # Target Format Dropdown
        self.format_label = ctk.CTkLabel(self.controls_frame, text="Format:", font=ctk.CTkFont(weight="bold"))
        self.format_label.pack(side="left", padx=(10, 5), pady=12)

        self.format_dropdown = ctk.CTkOptionMenu(
            self.controls_frame, 
            values=CATEGORY_MAP["Video"],
            width=100
        )
        self.format_dropdown.pack(side="left", padx=5, pady=12)

        # Stream Copy Checkbox
        self.stream_copy_var = ctk.BooleanVar(value=False)
        self.stream_copy_cb = ctk.CTkCheckBox(
            self.controls_frame, 
            text="⚡ Fast Remux (-c copy)", 
            variable=self.stream_copy_var,
            font=ctk.CTkFont(size=12)
        )
        self.stream_copy_cb.pack(side="left", padx=15, pady=12)

        # Action Buttons
        self.clear_btn = ctk.CTkButton(
            self.controls_frame, 
            text="Clear Queue", 
            fg_color="#D32F2F", 
            hover_color="#9A0007",
            width=100,
            command=self.clear_queue
        )
        self.clear_btn.pack(side="right", padx=15, pady=12)

        self.action_btn = ctk.CTkButton(
            self.controls_frame, 
            text="Start Batch", 
            fg_color="#2E7D32", 
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            width=110,
            command=self.toggle_batch_execution
        )
        self.action_btn.pack(side="right", padx=5, pady=12)

        # PROGRESS FOOTER 
        self.progress_frame = ctk.CTkFrame(self.tab_converter, corner_radius=10)
        self.progress_frame.grid(row=3, column=0, padx=5, pady=(5, 5), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.pack(fill="x", padx=15, pady=(12, 5))
        self.progress_bar.set(0)

        self.status_info_label = ctk.CTkLabel(
            self.progress_frame, 
            text="Ready to process", 
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.status_info_label.pack(side="left", padx=15, pady=(0, 10))

        self.open_folder_btn = ctk.CTkButton(
            self.progress_frame,
            text="📁 Open Output Folder",
            width=140,
            fg_color="#333333",
            hover_color="#444444",
            command=self._open_output_folder
        )

        # ==========================================
        # TAB 2: YOUTUBE DOWNLOADER
        # ==========================================
        self.tab_downloader.grid_columnconfigure(0, weight=1)
        
        # URL Input
        self.dl_input_frame = ctk.CTkFrame(self.tab_downloader, corner_radius=10)
        self.dl_input_frame.grid(row=0, column=0, padx=5, pady=10, sticky="ew")
        
        self.dl_url_label = ctk.CTkLabel(self.dl_input_frame, text="Video URL:", font=ctk.CTkFont(weight="bold"))
        self.dl_url_label.pack(side="left", padx=(15, 5), pady=15)
        
        self.dl_url_entry = ctk.CTkEntry(self.dl_input_frame, placeholder_text="Paste YouTube link here...")
        self.dl_url_entry.pack(side="left", padx=5, pady=15, fill="x", expand=True)
        
        self.dl_format_label = ctk.CTkLabel(self.dl_input_frame, text="Format:", font=ctk.CTkFont(weight="bold"))
        self.dl_format_label.pack(side="left", padx=(10, 5), pady=15)
        
        self.dl_format_dropdown = ctk.CTkOptionMenu(
            self.dl_input_frame, 
            values=["Video (Best MP4)", "Audio (MP3)"], 
            width=140
        )
        self.dl_format_dropdown.pack(side="left", padx=(5, 15), pady=15)

        # Destination Selector
        self.dl_dest_frame = ctk.CTkFrame(self.tab_downloader, corner_radius=10)
        self.dl_dest_frame.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        self.dl_dest_label = ctk.CTkLabel(self.dl_dest_frame, text="Save To:", font=ctk.CTkFont(weight="bold"))
        self.dl_dest_label.pack(side="left", padx=(15, 5), pady=8)

        self.dl_dest_entry = ctk.CTkEntry(self.dl_dest_frame, placeholder_text="Default: Downloads folder")
        self.dl_dest_entry.pack(side="left", padx=5, pady=8, fill="x", expand=True)
        self.dl_dest_entry.configure(state="disabled")

        self.dl_browse_btn = ctk.CTkButton(
            self.dl_dest_frame, text="Browse...", width=90, command=self._browse_dl_output_folder
        )
        self.dl_browse_btn.pack(side="left", padx=5, pady=8)

        self.dl_reset_btn = ctk.CTkButton(
            self.dl_dest_frame, text="Reset", width=60, fg_color="#555555", hover_color="#333333", command=self._reset_dl_output_folder
        )
        self.dl_reset_btn.pack(side="left", padx=(5, 15), pady=8)
        
        # Download Action & Progress
        self.dl_action_frame = ctk.CTkFrame(self.tab_downloader, corner_radius=10)
        self.dl_action_frame.grid(row=2, column=0, padx=5, pady=10, sticky="ew")
        
        self.dl_action_btn = ctk.CTkButton(
            self.dl_action_frame, 
            text="⬇️ Start Download", 
            fg_color="#2E7D32", 
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold", size=14),
            height=40,
            command=self.start_download
        )
        self.dl_action_btn.pack(pady=15, padx=15, fill="x")
        
        self.dl_progress_bar = ctk.CTkProgressBar(self.dl_action_frame)
        self.dl_progress_bar.pack(fill="x", padx=15, pady=(0, 5))
        self.dl_progress_bar.set(0)
        
        self.dl_status_label = ctk.CTkLabel(
            self.dl_action_frame, 
            text="Ready" if HAS_YTDLP else "⚠️ yt-dlp is missing. Please run: pip install yt-dlp", 
            font=ctk.CTkFont(size=12),
            text_color="gray" if HAS_YTDLP else "#EF5350"
        )
        self.dl_status_label.pack(side="left", padx=15, pady=(0, 15))

        self.dl_open_folder_btn = ctk.CTkButton(
            self.dl_action_frame,
            text="📁 Open Folder",
            width=120,
            fg_color="#333333",
            hover_color="#444444",
            command=self._open_dl_output_folder
        )
        self.dl_open_folder_btn.pack(side="right", padx=15, pady=(0, 15))


    # ==========================================
    # GLOBAL & CONVERTER METHODS (Unchanged)
    # ==========================================

    def _setup_shortcuts(self):
        """Bind lightweight keyboard shortcuts."""
        self.bind("<Control-o>", lambda e: self._open_file_dialog())
        self.bind("<Return>", lambda e: self.toggle_batch_execution())
        self.bind("<Delete>", lambda e: self.clear_queue())

    def _open_file_dialog(self):
        """Open system file picker via Ctrl+O."""
        files = filedialog.askopenfilenames(filetypes=FILE_TYPES)
        if files:
            for file_path in files:
                ext = os.path.splitext(file_path)[1].lower()
                if ext in SUPPORTED_EXTS:
                    if self.empty_label.winfo_exists():
                        self.empty_label.destroy()
                    self.add_file_to_queue(file_path)

    def _show_ffmpeg_warning(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("FFmpeg Missing")
        dialog.geometry("450x220")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        msg = ctk.CTkLabel(
            dialog, 
            text="⚠️ FFmpeg was not found.\n\nThis app expects ffmpeg.exe to be bundled next to it. If you're\nrunning from source, install FFmpeg and add it to PATH, or drop\nffmpeg.exe/ffprobe.exe into this app's folder.",
            wraplength=400,
            font=ctk.CTkFont(size=13)
        )
        msg.pack(pady=20, padx=20)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        dl_btn = ctk.CTkButton(
            btn_frame, 
            text="Download FFmpeg", 
            fg_color="#1976D2", 
            command=lambda: webbrowser.open("https://ffmpeg.org/download.html")
        )
        dl_btn.pack(side="left", padx=10)

        close_btn = ctk.CTkButton(btn_frame, text="Dismiss", fg_color="#555555", command=dialog.destroy)
        close_btn.pack(side="left", padx=10)

    def _browse_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.custom_output_dir = folder
            self.dest_entry.configure(state="normal")
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, folder)
            self.dest_entry.configure(state="disabled")

    def _reset_output_folder(self):
        self.custom_output_dir = ""
        self.dest_entry.configure(state="normal")
        self.dest_entry.delete(0, "end")
        self.dest_entry.configure(state="disabled")

    def _open_output_folder(self):
        target_dir = self.custom_output_dir if self.custom_output_dir else (
            os.path.dirname(self.file_queue[0]['path']) if self.file_queue else os.path.expanduser("~")
        )
        if os.path.exists(target_dir):
            if sys.platform == "win32":
                os.startfile(target_dir)
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", target_dir])

    def _on_category_change(self, selected_category):
        formats = CATEGORY_MAP.get(selected_category, [])
        self.format_dropdown.configure(values=formats)
        if formats:
            self.format_dropdown.set(formats[0])

    def _setup_dnd(self):
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self.handle_drop)

    def handle_drop(self, event):
        self.tabview.set("🔄 Converter") # Auto-switch to converter tab on drop
        files = self.parse_drop_files(event.data)
        if files:
            for file_path in files:
                if os.path.isfile(file_path):
                    ext = os.path.splitext(file_path)[1].lower()
                    if ext in SUPPORTED_EXTS:
                        if self.empty_label.winfo_exists():
                            self.empty_label.destroy()
                        self.add_file_to_queue(file_path)

    def parse_drop_files(self, data):
        if not data:
            return []
        if data.startswith('{'):
            return re.findall(r'\{([^}]+)\}', data)
        return data.split()

    def add_file_to_queue(self, path):
        if any(item['path'] == path for item in self.file_queue):
            return

        filename = os.path.basename(path)
        
        row = ctk.CTkFrame(self.queue_frame, corner_radius=6)
        row.pack(fill="x", padx=5, pady=4)

        name_lbl = ctk.CTkLabel(row, text=filename, font=ctk.CTkFont(weight="bold"), anchor="w")
        name_lbl.pack(side="left", padx=10, pady=8, expand=True, fill="x")

        status_lbl = ctk.CTkLabel(row, text="Queued", text_color="#FFA000", font=ctk.CTkFont(size=12))
        status_lbl.pack(side="right", padx=10, pady=8)

        remove_btn = ctk.CTkButton(
            row, text="✕", width=28, height=28, 
            fg_color="transparent", hover_color="#333333",
            command=lambda: self.remove_from_queue(path, row)
        )
        remove_btn.pack(side="right", padx=5)

        self.file_queue.append({
            'path': path, 
            'frame': row, 
            'status_lbl': status_lbl, 
            'remove_btn': remove_btn
        })

    def remove_from_queue(self, path, frame_widget):
        if self.is_processing:
            return
        self.file_queue = [item for item in self.file_queue if item['path'] != path]
        frame_widget.destroy()

    def clear_queue(self):
        if self.is_processing:
            return
        for item in self.file_queue:
            item['frame'].destroy()
        self.file_queue.clear()

    # PROCESSING ENGINE

    def get_duration(self, file_path):
        if FFPROBE_PATH:
            try:
                cmd = [
                    FFPROBE_PATH, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0", file_path
                ]
                process = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="ignore"
                )
                value = process.stdout.strip()
                if value:
                    return float(value)
            except Exception:
                pass

        # Fallback: parse ffmpeg -i stderr if ffprobe isn't available
        try:
            cmd = [FFMPEG_PATH, "-i", file_path]
            process = subprocess.run(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, creationflags=CREATE_NO_WINDOW, encoding="utf-8", errors="ignore"
            )
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", process.stderr)
            if match:
                hrs, mins, secs = map(float, match.groups())
                return hrs * 3600 + mins * 60 + secs
        except Exception:
            pass
        return None

    def build_ffmpeg_cmd(self, input_path, output_path, target_ext, is_stream_copy):
        cmd = [FFMPEG_PATH, "-y"]

        if self.gpu_type != "cpu" and not is_stream_copy:
            cmd.extend(["-hwaccel", "auto"])

        cmd.extend(["-i", input_path])

        if is_stream_copy:
            cmd.extend(["-c", "copy"])
        else:
            if target_ext in AUDIO_TARGET_KEYS:
                cmd.extend(["-vn"])
                if target_ext == "mp3":
                    cmd.extend(["-codec:a", "libmp3lame", "-b:a", "192k"])
                elif target_ext == "aac":
                    cmd.extend(["-c:a", "aac", "-b:a", "192k"])
                elif target_ext == "opus":
                    cmd.extend(["-c:a", "libopus", "-b:a", "128k"])
                elif target_ext == "flac":
                    cmd.extend(["-c:a", "flac"])
            elif target_ext in STATIC_IMAGE_KEYS:
                cmd.extend(["-vframes", "1"])
            elif target_ext == "gif":
                # Two-pass palette generation gives noticeably cleaner, less banded
                # GIFs than the default fixed web-safe palette, for negligible extra cost.
                cmd.extend([
                    "-vf",
                    "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
                ])
            elif target_ext in VIDEO_TARGET_KEYS:
                if self.gpu_type == "amf":
                    cmd.extend(["-c:v", "h264_amf", "-quality", "speed"])
                elif self.gpu_type == "nvenc":
                    cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"])
                elif self.gpu_type == "qsv":
                    cmd.extend(["-c:v", "h264_qsv", "-preset", "veryfast"])
                else:
                    cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])

        cmd.extend(["-progress", "pipe:1", "-nostdin", output_path])
        return cmd

    def toggle_batch_execution(self):
        if not self.ffmpeg_available:
            self._show_ffmpeg_warning()
            return

        if self.is_processing:
            self.cancel_batch()
        else:
            self.start_processing()

    def start_processing(self):
        if not self.file_queue or self.is_processing:
            return

        self.is_processing = True
        self.cancel_requested = False
        self.completed_count = 0
        self.active_processes.clear()
        self.file_progress = {item['path']: 0.0 for item in self.file_queue}

        self.open_folder_btn.pack_forget()

        self.action_btn.configure(
            text="Cancel Batch", 
            fg_color="#D32F2F", 
            hover_color="#9A0007"
        )
        self.clear_btn.configure(state="disabled")
        self.browse_btn.configure(state="disabled")
        self.reset_dest_btn.configure(state="disabled")
        self.cat_dropdown.configure(state="disabled")
        self.format_dropdown.configure(state="disabled")

        threading.Thread(target=self._batch_executor, daemon=True).start()

    def cancel_batch(self):
        self.cancel_requested = True
        self.status_info_label.configure(text="Cancelling processing...")

        with self.queue_lock:
            for process in self.active_processes:
                try:
                    process.kill()
                except Exception:
                    pass
            self.active_processes.clear()

    def _convert_file_worker(self, item, target_ext, is_stream_copy):
        if self.cancel_requested:
            return

        input_path = item['path']
        self.after(0, lambda: item['status_lbl'].configure(text="Converting...", text_color="#29B6F6"))

        filename = os.path.basename(input_path)
        base, _ = os.path.splitext(filename)
        output_filename = f"{base}_converted.{target_ext}"

        if self.custom_output_dir and os.path.exists(self.custom_output_dir):
            output_path = os.path.join(self.custom_output_dir, output_filename)
        else:
            output_path = os.path.join(os.path.dirname(input_path), output_filename)

        total_duration = self.get_duration(input_path)
        cmd = self.build_ffmpeg_cmd(input_path, output_path, target_ext, is_stream_copy)

        success = False
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                encoding="utf-8",
                errors="ignore"
            )

            with self.queue_lock:
                self.active_processes.append(process)

            for line in iter(process.stdout.readline, ''):
                if self.cancel_requested:
                    break

                line = line.strip()
                if line.startswith("out_time_us=") and total_duration:
                    try:
                        microsecs = int(line.split("=")[1])
                        current_secs = microsecs / 1_000_000
                        pct = min(current_secs / total_duration, 1.0)
                        self.after(0, lambda p=pct: self._on_convert_progress(item, p))
                    except ValueError:
                        pass

            process.stdout.close()
            process.wait()

            with self.queue_lock:
                if process in self.active_processes:
                    self.active_processes.remove(process)

            if process.returncode == 0 and not self.cancel_requested:
                success = True

        except Exception:
            success = False

        # Cleanup & Status Updates
        if self.cancel_requested:
            self.after(0, lambda: item['status_lbl'].configure(text="Cancelled ⚠️", text_color="#FFA000"))
            if os.path.exists(output_path):
                try: os.remove(output_path)
                except Exception: pass
        elif success:
            self.after(0, lambda: item['status_lbl'].configure(text="Completed ✅", text_color="#66BB6A"))
            self.after(0, lambda: self._finalize_file_progress(item['path']))
        else:
            self.after(0, lambda: item['status_lbl'].configure(text="Failed ❌", text_color="#EF5350"))
            self.after(0, lambda: self._finalize_file_progress(item['path']))
            # Purge partial/corrupted output file on failure
            if os.path.exists(output_path):
                try: os.remove(output_path)
                except Exception: pass

        with self.queue_lock:
            self.completed_count += 1
            progress_ratio = self.completed_count / len(self.file_queue)
            self.after(0, self._update_overall_progress, progress_ratio, self.completed_count, len(self.file_queue))

    def _batch_executor(self):
        target_ext = self.format_dropdown.get().lower()
        is_stream_copy = self.stream_copy_var.get()

        # Dynamic Core-Aware Threading (Max 4 workers, min 1, scales to hardware).
        # GPU encoders (NVENC/AMF/QSV) commonly cap concurrent encode sessions on
        # consumer hardware, so we deliberately keep the pool smaller when a
        # hardware encoder is in play to avoid stalled/failed sessions.
        cpu_cores = os.cpu_count() or 2
        if self.gpu_type != "cpu" and not is_stream_copy:
            max_workers = 2
        else:
            max_workers = max(1, min(cpu_cores // 2, 4))
        max_workers = min(max_workers, len(self.file_queue))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._convert_file_worker, item, target_ext, is_stream_copy)
                for item in self.file_queue
            ]
            for future in futures:
                future.result()

        self.after(0, self._finish_batch)

    def _on_convert_progress(self, item, pct):
        """Called on the main thread as a single file's FFmpeg progress updates."""
        item['status_lbl'].configure(text=f"{int(pct * 100)}%", text_color="#29B6F6")
        self.file_progress[item['path']] = pct
        self._refresh_progress_bar()

    def _finalize_file_progress(self, path):
        """Called on the main thread once a file's conversion has resolved (success/failure)."""
        self.file_progress[path] = 1.0
        self._refresh_progress_bar()

    def _refresh_progress_bar(self):
        """Recomputes the bottom progress bar as the average progress across all queued files."""
        if self.cancel_requested or not self.file_queue:
            return
        aggregate = sum(self.file_progress.values()) / len(self.file_queue)
        self.progress_bar.set(aggregate)

    def _update_overall_progress(self, ratio, current, total):
        if not self.cancel_requested:
            self.status_info_label.configure(text=f"Batch Progress: {current} of {total} files completed ({int(ratio * 100)}%)")

    def _finish_batch(self):
        self.is_processing = False
        self.action_btn.configure(
            text="Start Batch", 
            fg_color="#2E7D32", 
            hover_color="#1B5E20"
        )
        self.clear_btn.configure(state="normal")
        self.browse_btn.configure(state="normal")
        self.reset_dest_btn.configure(state="normal")
        self.cat_dropdown.configure(state="normal")
        self.format_dropdown.configure(state="normal")

        if self.cancel_requested:
            self.status_info_label.configure(text="Batch Cancelled by User")
        else:
            self.progress_bar.set(1.0)
            self.status_info_label.configure(text="Batch Processing Complete!")
            self.open_folder_btn.pack(side="right", padx=15, pady=(0, 10))

    # ==========================================
    # YOUTUBE DOWNLOADER METHODS
    # ==========================================

    def _browse_dl_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.dl_custom_output_dir = folder
            self.dl_dest_entry.configure(state="normal")
            self.dl_dest_entry.delete(0, "end")
            self.dl_dest_entry.insert(0, folder)
            self.dl_dest_entry.configure(state="disabled")

    def _reset_dl_output_folder(self):
        self.dl_custom_output_dir = ""
        self.dl_dest_entry.configure(state="normal")
        self.dl_dest_entry.delete(0, "end")
        self.dl_dest_entry.configure(state="disabled")

    def _open_dl_output_folder(self):
        target_dir = self.dl_custom_output_dir if self.dl_custom_output_dir else os.path.expanduser("~/Downloads")
        if os.path.exists(target_dir):
            if sys.platform == "win32":
                os.startfile(target_dir)
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", target_dir])

    def start_download(self):
        url = self.dl_url_entry.get().strip()
        if not url: 
            return
            
        if not HAS_YTDLP:
            self.dl_status_label.configure(text="⚠️ yt-dlp.exe not found next to the app.", text_color="#EF5350")
            return
            
        self.dl_action_btn.configure(state="disabled", text="Downloading...")
        self.dl_progress_bar.set(0)
        self.dl_status_label.configure(text="Initializing download...", text_color="gray")
        
        threading.Thread(target=self._download_worker, args=(url,), daemon=True).start()
        
    # Matches lines like:
    # [download]  42.7% of  118.34MiB at    3.21MiB/s ETA 00:22
    _DL_PROGRESS_RE = re.compile(
        r"\[download\]\s+(\d{1,3}(?:\.\d)?)%\s+of\s+\S+\s+at\s+(\S+)\s+ETA\s+(\S+)"
    )

    def _download_worker(self, url):
        format_choice = self.dl_format_dropdown.get()
        out_dir = self.dl_custom_output_dir or os.path.expanduser("~/Downloads")
        os.makedirs(out_dir, exist_ok=True)

        outtmpl = os.path.join(out_dir, "%(title)s.%(ext)s")

        cmd = [YTDLP_PATH, "--newline", "--no-playlist", "-o", outtmpl]

        # Point yt-dlp at the bundled ffmpeg so it never falls back to PATH.
        if FFMPEG_PATH:
            cmd.extend(["--ffmpeg-location", os.path.dirname(FFMPEG_PATH)])

        if format_choice == "Audio (MP3)":
            cmd.extend([
                "-f", "bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "192",
            ])
        else:
            cmd.extend([
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
            ])

        cmd.append(url)

        success = False
        error_msg = ""
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=CREATE_NO_WINDOW,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
            )

            last_lines = []
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if not line:
                    continue
                last_lines.append(line)
                last_lines = last_lines[-5:]  # keep a short tail for error reporting

                match = self._DL_PROGRESS_RE.search(line)
                if match:
                    pct = float(match.group(1)) / 100.0
                    speed = match.group(2)
                    eta = match.group(3)
                    self.after(0, self._update_dl_progress, pct, speed, eta)
                elif line.startswith("[Merger]") or line.startswith("[ExtractAudio]") or line.startswith("[ffmpeg]"):
                    self.after(0, lambda: self.dl_status_label.configure(
                        text="Finishing up / Converting (Please wait)...",
                        text_color="#29B6F6"
                    ))

            process.stdout.close()
            process.wait()

            if process.returncode == 0:
                success = True
            else:
                error_msg = " | ".join(last_lines)

        except Exception as e:
            error_msg = str(e)

        self.after(0, self._download_complete, success, error_msg)

    def _update_dl_progress(self, pct, speed, eta):
        self.dl_progress_bar.set(pct)
        self.dl_status_label.configure(text=f"Downloading: {int(pct*100)}% | Speed: {speed} | ETA: {eta}")

    def _download_complete(self, success, error=None):
        self.dl_action_btn.configure(state="normal", text="⬇️ Start Download")
        if success:
            self.dl_progress_bar.set(1.0)
            self.dl_status_label.configure(text="Download Complete! ✅", text_color="#66BB6A")
            self.dl_url_entry.delete(0, 'end')
        else:
            short_error = (error or "Check URL or network")[-120:]
            self.dl_status_label.configure(text=f"Error ❌ {short_error}", text_color="#EF5350")


if __name__ == "__main__":
    app = ModernConverterApp()
    app.mainloop()
