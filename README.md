# 🎬 Universal Media Toolkit

A lightweight desktop app for batch converting video, audio, and image files, plus downloading YouTube video/audio — all wrapped in a clean, modern dark-mode UI. No external installs required; FFmpeg and yt-dlp ship bundled with the app.

## Features

- **Batch conversion** — drag & drop (or file-picker) queue of video, audio, and image files, converted in parallel
- **Hardware-accelerated encoding** — automatically detects and uses NVIDIA NVENC, AMD AMF, or Intel QSV when available, falling back to CPU (libx264) otherwise
- **Fast Remux mode** — stream-copy (`-c copy`) for near-instant container swaps without re-encoding
- **Live progress** — per-file percentage plus a smoothly animated overall batch progress bar
- **YouTube downloader** — grab video (MP4) or audio-only (MP3) from a URL, with live download progress
- **Zero setup for end users** — FFmpeg, FFprobe, and yt-dlp are bundled; nothing extra to install

## Download

Grab the latest installer from the [**Releases**](../../releases) page — `Universal Media Toolkit-Setup-vX.X.X.exe`. Run it, follow the installer, and launch the app from your Start Menu or Desktop shortcut.

> **Note:** This app isn't currently code-signed, so Windows SmartScreen may show an "unknown publisher" warning on first run. Click **More info → Run anyway** to proceed. This is expected for small open-source tools without a paid code-signing certificate — the source is fully visible in this repo if you'd like to verify what's being run.

## Requirements (running from source)

If you'd rather run from source instead of the installer:

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) and `ffprobe` on your PATH (or placed next to `converter.py`)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp/releases) on your PATH (or placed next to `converter.py`) — only needed for the Downloader tab

```bash
pip install customtkinter tkinterdnd2
python converter.py
```

## Building the installer yourself

This project builds to a standalone Windows executable via [Nuitka](https://nuitka.net/), then packages that into a proper installer via [Inno Setup](https://jrsoftware.org/isdl.php) — so end users never see the raw DLLs/binaries, just a normal Setup.exe.

**1. Grab the bundled binaries** (not included in this repo — see [`.gitignore`](.gitignore)) and place them next to `converter.py`:
- `ffmpeg.exe` + `ffprobe.exe` — static build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases) (LGPL build recommended)
- `yt-dlp.exe` — from the [official releases](https://github.com/yt-dlp/yt-dlp/releases)

**2. Compile with Nuitka:**
```bash
python -m nuitka --standalone --enable-plugin=tk-inter --windows-console-mode=disable --include-package-data=customtkinter --include-package-data=tkinterdnd2 --include-data-files=ffmpeg.exe=ffmpeg.exe --include-data-files=ffprobe.exe=ffprobe.exe --include-data-files=yt-dlp.exe=yt-dlp.exe --include-data-files=icon.ico=icon.ico --windows-icon-from-ico=icon.ico --low-memory converter.py
```
This produces a `converter.dist/` folder.

**3. Build the installer:**
Open `installer.iss` in [Inno Setup](https://jrsoftware.org/isdl.php) and compile (or `iscc installer.iss` from the command line). The finished installer lands in `Output/`.

## Usage

- **Converter tab** — drag files into the queue (or `Ctrl+O`), pick a category and target format, optionally enable Fast Remux, then hit Start Batch (`Enter`).
- **YouTube Downloader tab** — paste a URL, pick Video or Audio, and hit Start Download.

## A note on the YouTube Downloader

This feature is intended for downloading content you have the rights to (your own uploads, permissively licensed material, content you have explicit permission to save, etc.). Downloading copyrighted content without authorization may violate YouTube's Terms of Service and/or applicable copyright law depending on your jurisdiction. Use responsibly.

## Third-Party Software

This app bundles FFmpeg, FFprobe, and yt-dlp as separate executables, and uses CustomTkinter and tkinterdnd2 as Python libraries. See [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) for full attribution and license details.

## License

This project's own source code is licensed under the [MIT License](LICENSE). Bundled third-party components retain their own licenses — see above.
