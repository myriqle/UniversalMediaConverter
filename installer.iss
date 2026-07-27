; ============================================================
; Universal Media Toolkit - Inno Setup Installer Script
; ============================================================
; This packages the entire Nuitka --standalone output folder
; (converter.dist) into a single Setup.exe. End users only ever
; see a normal installer and a Start Menu / Desktop shortcut -
; they never browse the folder full of DLLs, ffmpeg.exe, etc.
;
; HOW TO USE:
; 1. Install Inno Setup (free): https://jrsoftware.org/isdl.php
; 2. Build your app first: python -m nuitka --standalone ... converter.py
;    (this produces the "converter.dist" folder)
; 3. Edit the SourceDir line below if your dist folder isn't
;    named "converter.dist" or isn't next to this script.
; 4. Open this file in Inno Setup and click Build > Compile
;    (or run: iscc installer.iss  from the command line)
; 5. Your installer appears in the "Output" folder as Setup.exe
; ============================================================

#define MyAppName "Universal Media Toolkit"
#define MyAppVersion "1.4.0"
#define MyAppPublisher "Josh Niemand"
#define MyAppExeName "converter.exe"
#define MyAppIcon "icon.ico"

; Folder produced by your Nuitka --standalone build.
; Change this if your build output lives somewhere else.
#define SourceDir "converter.dist"

[Setup]
AppId={{B4A1F6E2-9C3D-4A7B-8E2F-1D6C5A9B3E4F}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Where the compiled Setup.exe gets written to
OutputDir=Output
OutputBaseFilename={#MyAppName}-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Shows your icon in Explorer, the installer itself, and Add/Remove Programs
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
; No admin rights required - installs to the user's own AppData\Local
; instead of Program Files. Switch to "admin" + {autopf} above if you'd
; rather require elevation and install machine-wide for all users.
PrivilegesRequired=lowest
;DefaultDirName={autopf}\{#MyAppName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Pulls in EVERYTHING from the dist folder (converter.exe, all DLLs,
; ffmpeg.exe, ffprobe.exe, yt-dlp.exe, icon.ico, customtkinter/tkinterdnd2
; data, etc.) and drops it flat into the install directory.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppIcon}"
; Optional desktop shortcut (only created if the user ticks the box above)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppIcon}"; Tasks: desktopicon
; Uninstaller entry in the Start Menu
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Offers to launch the app immediately after install finishes
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Ensures the whole install folder is removed on uninstall, including
; any files the app itself might have written there (e.g. logs/config)
Type: filesandordirs; Name: "{app}"
