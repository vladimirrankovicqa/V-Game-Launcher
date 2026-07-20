<div align="center">

# V Game Launcher

A modern Windows desktop launcher for organizing and starting games from one unified library.

[![Latest Release](https://img.shields.io/github/v/release/vladimirrankovicqa/V-Game-Launcher?style=for-the-badge&label=Latest%20Release)](https://github.com/vladimirrankovicqa/V-Game-Launcher/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows11&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)

<br>

<img src="images/hero-library.png" alt="V Game Launcher Library" width="900">

<br><br>

[Download Latest Release](https://github.com/vladimirrankovicqa/V-Game-Launcher/releases/latest) ·
[Report an Issue](https://github.com/vladimirrankovicqa/V-Game-Launcher/issues) ·
[View Source](https://github.com/vladimirrankovicqa/V-Game-Launcher)

</div>

---

## Overview

**V Game Launcher** is a Windows desktop application built with Python and PySide6. It brings games from multiple sources into one clean and customizable library.

The launcher can import supported installed games, add local executables manually, display cover artwork, organize favorites, track recently played titles, and launch games directly from the application.

## Features

- Unified game library
- Automatic import of installed Steam games
- Import support for Epic Games titles
- Detection of supported EA App / Origin games
- Detection of supported GOG games
- Manual import for local games and executables
- Cover image downloading and management
- Favorites collection
- Recently Played section
- Search and sorting controls
- Game running-state indication
- Prevention of multiple simultaneous game launches
- Dark and light theme support
- Configurable Steam executable and library folder
- Automatic version checking
- Direct access to GitHub Releases when an update is available
- Custom application and taskbar icon
- Portable standalone Windows executable

## Download

Download the newest Windows executable from the project's **Releases** page:

### [Download the latest release](https://github.com/vladimirrankovicqa/V-Game-Launcher/releases/latest)

The application is portable and does not require a traditional installer.

> [!NOTE]
> Windows SmartScreen may display a warning because the executable is not digitally signed. Download releases only from this official repository.

## Screenshots

### Game Library

<img src="images/hero-library.png" alt="V Game Launcher Library" width="900">

### Import Installed Games

<img src="images/import-games.png" alt="Import Installed Games" width="900">

### Preferences

<img src="images/preferences.png" alt="V Game Launcher Preferences" width="900">

### About

<img src="images/about.png" alt="V Game Launcher About Page" width="900">

## How to Use

1. Open **V Game Launcher**.
2. Import installed games from a supported launcher or add a local game manually.
3. Review and edit the game name, executable path, and cover image when needed.
4. Use Search, Favorites, Recently Played, or sorting controls to organize the library.
5. Select **Play** to launch a game.

## Running From Source

### Requirements

- Windows
- Python 3
- Dependencies listed in `requirements.txt`

Clone the repository:

```powershell
git clone https://github.com/vladimirrankovicqa/V-Game-Launcher.git
cd V-Game-Launcher
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run the application:

```powershell
python v_game_launcher.py
```

## Build the Windows Executable

Install PyInstaller:

```powershell
python -m pip install --upgrade pyinstaller
```

Build the standalone executable:

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "V Game Launcher" --icon "v_game_launcher.ico" "v_game_launcher.py"
```

The completed executable will be created in:

```text
dist/V Game Launcher.exe
```

## Project Structure

```text
V-Game-Launcher/
├── images/
│   ├── about.png
│   ├── hero-library.png
│   ├── import-games.png
│   └── preferences.png
├── requirements.txt
├── resources.qrc
├── resources_rc.py
├── v_game_launcher.ico
├── v_game_launcher.png
└── v_game_launcher.py
```

## Technology Stack

- **Python** — application logic
- **PySide6 / Qt** — desktop interface
- **PyInstaller** — standalone Windows packaging
- **Steam library data and local launcher manifests** — game discovery
- **GitHub Releases** — application distribution and update access

## Roadmap

- [x] Steam game import
- [x] Manual local game import
- [x] Epic Games, EA App / Origin, and GOG detection
- [x] Favorites and Recently Played
- [x] Search and sorting
- [x] Dark and light themes
- [x] Update checking with GitHub Releases link
- [ ] Additional launcher integrations
- [ ] Optional game metadata editing
- [ ] Library backup and restore
- [ ] Expanded cover-image sources
- [ ] Additional interface customization

## Data and Privacy

V Game Launcher stores application preferences and library information locally on the user's computer. It does not require a launcher account password.

## Contributing

Suggestions, bug reports, and improvement ideas are welcome.

Use [GitHub Issues](https://github.com/vladimirrankovicqa/V-Game-Launcher/issues) to report a problem or propose a feature.

## Author

Created by **Vladimir Rankovic**.

[GitHub Profile](https://github.com/vladimirrankovicqa) ·
[LinkedIn Profile](https://www.linkedin.com/in/vladimir-rankovic-363814116/)

---

<div align="center">

One library. All your games.

Give the repository a star if the project is useful to you.

</div>
