# V Game Launcher

V Game Launcher is a Windows desktop application for managing and launching games from one place.

## Features

- Import installed Steam and Epic Games titles
- Detect selected GOG and EA App games
- Add local games and custom launch targets manually
- Download and manage game cover images
- Favorites and library filtering
- Steam account and online/offline launch options
- Automatic check for newer versions
- Direct link to the latest GitHub Release
- Local settings and library data stored in the user's AppData folder

## Current Version

**2.0.0**

## Requirements

- Windows 10 or Windows 11
- Python 3.13 recommended for building from source
- Dependencies listed in `requirements.txt`

## Run From Source

```powershell
python -m pip install -r requirements.txt
python v_game_launcher.py
```

## Build the Windows EXE

```powershell
python -m PyInstaller --noconfirm --clean --windowed --onefile `
--name "V_Game_Launcher" `
--icon "v_game_launcher.ico" `
"v_game_launcher.py"
```

The executable will be created at:

```text
dist\V_Game_Launcher.exe
```

## Updates

The application checks GitHub for newer published versions. When an update is available, the popup shows the current and latest version and provides a button to open the official GitHub Releases page.

Updates are downloaded and installed manually.

## Project Files

```text
v_game_launcher.py
resources_rc.py
v_game_launcher.ico
requirements.txt
README.md
.gitignore
```

## Download

Download the latest Windows executable from the repository's **Releases** section.

## License

No license has been added yet. All rights are reserved unless a license file is added later.
