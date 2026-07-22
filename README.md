# ⚡ Universal Media Converter

A high-performance, standalone desktop application for Windows that converts Video, Audio, and Images with end-to-end GPU hardware acceleration (NVENC, AMF, QSV).

## ✨ Features
* **GPU Hardware Acceleration:** Full GPU decoding and encoding pipelines (`-hwaccel` + NVENC/AMF/QSV).
* **Drag and Drop Interface:** Easy batch conversion using `tkinterdnd2`.
* **Silent Execution:** Processes run seamlessly in the background without command prompt popups.
* **Collapsible Live Logs:** Clean interface with full real-time console log inspectability.

## 🚀 Running from Source
1. **Clone the repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/universal-media-converter.git](https://github.com/YOUR_USERNAME/universal-media-converter.git)
   cd universal-media-converter
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Place FFmpeg:** Download `ffmpeg.exe` and place it in the project root directory.
4. **Run the app:**
   ```bash
   python converter.py
   ```

## 🛠️ Building the Executable (Nuitka)
To build a standalone single-file binary:
```bash
python -m nuitka --standalone --onefile --enable-plugin=tk-inter --include-package-data=tkinterdnd2 --windows-console-mode=disable --include-data-file=ffmpeg.exe=ffmpeg.exe converter.py
```

## 📜 License
Distributed under the [MIT License](LICENSE).
