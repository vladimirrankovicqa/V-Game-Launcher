from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import resources_rc
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    import winreg
except ImportError:
    winreg = None

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QScrollArea,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "V Game Launcher"
APP_VERSION = "2.0.1"

GITHUB_REPOSITORY_URL = "https://github.com/vladimirrankovicqa/V-Game-Launcher"
GITHUB_RELEASES_URL = f"{GITHUB_REPOSITORY_URL}/releases"
GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/vladimirrankovicqa/V-Game-Launcher/releases/latest"
GITHUB_API_VERSION = "2026-03-10"
PREFERRED_UPDATE_ASSET_NAMES = ("V_Game_Launcher.exe", "V-Game-Launcher.exe", "V.Game.Launcher.exe", "V Game Launcher.exe")
UPDATE_CHECK_TIMEOUT = 10
UPDATE_DOWNLOAD_TIMEOUT = 45
MAX_UPDATE_DOWNLOAD_BYTES = 500 * 1024 * 1024
CARD_WIDTH = 220
CARD_HEIGHT = 355
COVER_WIDTH = 198
COVER_HEIGHT = 255

BG_DEEPEST = "#0b1017"
BG_SIDEBAR = "#111821"
BG_MAIN = "#171d25"
BG_PANEL = "#1b2838"
BG_PANEL_HOVER = "#22384d"
BG_INPUT = "#101822"
BORDER = "#2b4055"
TEXT_PRIMARY = "#f2f5f8"
TEXT_SECONDARY = "#8f98a0"
ACCENT_BLUE = "#1a9fff"
ACCENT_BLUE_HOVER = "#36b4ff"
ACCENT_GREEN = "#75b022"
ACCENT_GREEN_HOVER = "#8bc53f"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_data_directory() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "VGameLauncher"
        return Path.home() / "AppData" / "Local" / "VGameLauncher"
    return Path.home() / ".local" / "share" / "VGameLauncher"


APP_DIR = app_directory()
DATA_DIR = user_data_directory()
DATA_FILE = DATA_DIR / "games.json"
SETTINGS_FILE = DATA_DIR / "launcher_settings.json"
COVERS_DIR = DATA_DIR / "assets" / "covers"
LEGACY_DATA_FILE = APP_DIR / "games.json"
LEGACY_SETTINGS_FILE = APP_DIR / "launcher_settings.json"
LEGACY_COVERS_DIR = APP_DIR / "assets" / "covers"
UPDATE_DIR = DATA_DIR / "updates"


def parsed_version(value: str) -> tuple[int, int, int] | None:
    # Parse tags such as v2.1, 2.1.0 or release-2.1.0 into a comparable tuple.
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", value.strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    candidate_version = parsed_version(candidate)
    current_version = parsed_version(current)
    return bool(candidate_version and current_version and candidate_version > current_version)


def github_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"VGameLauncher/{APP_VERSION} (Windows; updater)",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )


def update_download_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"VGameLauncher/{APP_VERSION} (Windows; updater)",
        },
    )


def select_release_asset(assets: Any) -> dict[str, Any] | None:
    if not isinstance(assets, list):
        return None
    executable_assets = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("state", "uploaded")).casefold() == "uploaded"
        and str(asset.get("name", "")).casefold().endswith(".exe")
        and str(asset.get("browser_download_url", "")).startswith("https://")
    ]
    if not executable_assets:
        return None

    preferred = {name.casefold(): index for index, name in enumerate(PREFERRED_UPDATE_ASSET_NAMES)}
    exact_matches = [asset for asset in executable_assets if str(asset.get("name", "")).casefold() in preferred]
    if exact_matches:
        exact_matches.sort(key=lambda asset: preferred[str(asset.get("name", "")).casefold()])
        return exact_matches[0]

    portable_matches = [
        asset
        for asset in executable_assets
        if "launcher" in str(asset.get("name", "")).casefold()
        and not any(token in str(asset.get("name", "")).casefold() for token in ("setup", "installer", "uninstall"))
    ]
    if len(portable_matches) == 1:
        return portable_matches[0]
    if len(executable_assets) == 1:
        return executable_assets[0]
    return None


def latest_release_information() -> dict[str, Any]:
    request = github_request(GITHUB_LATEST_RELEASE_API)
    try:
        with urlopen(request, timeout=UPDATE_CHECK_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
    except HTTPError as error:
        if error.code == 404:
            raise RuntimeError("No published GitHub release was found yet.") from error
        if error.code == 403:
            raise RuntimeError("GitHub temporarily refused the update check, possibly because of an API rate limit.") from error
        raise RuntimeError(f"GitHub returned HTTP {error.code} while checking for updates.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError("The update server could not be reached. Check the internet connection and try again.") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("GitHub returned an invalid update response.") from error

    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an unexpected update response.")

    latest_version = str(payload.get("tag_name", "")).strip()
    if parsed_version(latest_version) is None:
        raise RuntimeError("The latest GitHub release does not have a valid version tag.")

    asset = select_release_asset(payload.get("assets", []))
    return {
        "latest_version": latest_version,
        "release_name": str(payload.get("name", latest_version)).strip() or latest_version,
        "release_url": str(payload.get("html_url", GITHUB_RELEASES_URL)).strip() or GITHUB_RELEASES_URL,
        "release_notes": str(payload.get("body", "")).strip(),
        "published_at": str(payload.get("published_at", "")).strip(),
        "asset": asset,
    }


def updater_safe_batch_value(value: str) -> str:
    return value.replace("%", "%%")


def create_windows_update_script(downloaded_executable: Path, target_executable: Path) -> Path:
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    script_path = UPDATE_DIR / f"apply_update_{uuid.uuid4().hex}.cmd"
    backup_path = target_executable.with_suffix(target_executable.suffix + ".old")
    target = updater_safe_batch_value(str(target_executable))
    source = updater_safe_batch_value(str(downloaded_executable))
    backup = updater_safe_batch_value(str(backup_path))
    pid = os.getpid()
    script = f'''@echo off
setlocal
set "TARGET={target}"
set "SOURCE={source}"
set "BACKUP={backup}"

:wait_for_launcher
tasklist /FI "PID eq {pid}" /NH 2>NUL | findstr /R /C:"[ ]{pid}[ ]" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait_for_launcher
)

if exist "%BACKUP%" del /F /Q "%BACKUP%" >NUL 2>&1
if exist "%TARGET%" move /Y "%TARGET%" "%BACKUP%" >NUL
move /Y "%SOURCE%" "%TARGET%" >NUL
if errorlevel 1 goto restore_old_version

if exist "%BACKUP%" del /F /Q "%BACKUP%" >NUL 2>&1
start "" "%TARGET%"
goto cleanup

:restore_old_version
if exist "%BACKUP%" move /Y "%BACKUP%" "%TARGET%" >NUL
if exist "%TARGET%" start "" "%TARGET%"

:cleanup
endlocal
(goto) 2>NUL & del /F /Q "%~f0"
'''
    script_path.write_text(script, encoding="utf-8", newline="\r\n")
    return script_path


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
    except (OSError, json.JSONDecodeError):
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temporary.replace(path)


def normalize_path(value: str) -> str:
    return os.path.normpath(os.path.expandvars(value.strip().strip('"')))


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path_resolved = path.resolve()
        parent_resolved = parent.resolve()
        common = os.path.commonpath([str(path_resolved), str(parent_resolved)])
        return common.casefold() == str(parent_resolved).casefold()
    except (OSError, ValueError):
        return False


def migrate_legacy_data() -> bool:
    """Move portable v2.0 data into the per-user AppData directory once."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    if APP_DIR.resolve() == DATA_DIR.resolve():
        return False

    migrated_anything = False

    try:
        if LEGACY_COVERS_DIR.is_dir():
            for source in LEGACY_COVERS_DIR.iterdir():
                if not source.is_file():
                    continue
                destination = COVERS_DIR / source.name
                if not destination.exists():
                    shutil.copy2(source, destination)
                    migrated_anything = True
    except OSError:
        pass

    if not SETTINGS_FILE.exists() and LEGACY_SETTINGS_FILE.is_file():
        try:
            shutil.copy2(LEGACY_SETTINGS_FILE, SETTINGS_FILE)
            migrated_anything = True
        except OSError:
            pass

    if not DATA_FILE.exists() and LEGACY_DATA_FILE.is_file():
        legacy_games = load_json(LEGACY_DATA_FILE, [])
        if isinstance(legacy_games, list):
            remapped_games: list[Any] = []
            for item in legacy_games:
                if not isinstance(item, dict):
                    continue
                record = dict(item)
                cover_value = str(record.get("cover", "")).strip()
                if cover_value:
                    cover_path = Path(cover_value)
                    candidate = COVERS_DIR / cover_path.name
                    if path_is_within(cover_path, LEGACY_COVERS_DIR) or (not cover_path.exists() and candidate.exists()):
                        record["cover"] = str(candidate)
                remapped_games.append(record)
            try:
                save_json(DATA_FILE, remapped_games)
                migrated_anything = True
            except OSError:
                pass

    return migrated_anything


def delete_unused_cover(cover_value: str, games: list[dict[str, Any]]) -> None:
    if not cover_value:
        return
    cover_path = Path(cover_value)
    if not cover_path.is_file() or not path_is_within(cover_path, COVERS_DIR):
        return
    target = str(cover_path.resolve()).casefold()
    for game in games:
        other = str(game.get("cover", "")).strip()
        if not other:
            continue
        try:
            if str(Path(other).resolve()).casefold() == target:
                return
        except OSError:
            continue
    try:
        cover_path.unlink()
    except OSError:
        pass


def copy_cover_to_library(source: str) -> str:
    if not source:
        return ""
    source_path = Path(source)
    if not source_path.is_file():
        return source
    if path_is_within(source_path, COVERS_DIR):
        return str(source_path.resolve())
    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        destination = COVERS_DIR / f"{uuid.uuid4().hex}{source_path.suffix.lower()}"
        shutil.copy2(source_path, destination)
        return str(destination)
    except OSError:
        return source


COVER_DOWNLOAD_TIMEOUT = 12
MAX_COVER_DOWNLOAD_BYTES = 12 * 1024 * 1024
COVER_USER_AGENT = f"VGameLauncher/{APP_VERSION} (Windows; cover downloader)"


def cover_file_key(game: dict[str, Any]) -> str:
    platform = str(game.get("platform", "game")).strip().casefold()
    if platform == "steam":
        identifier = str(game.get("steam_app_id", "")).strip()
        if identifier:
            return f"steam_{identifier}"
    if platform == "epic games":
        identifier = str(game.get("epic_catalog_item_id", "")).strip()
        if identifier:
            return f"epic_{identifier}"
    identifier = str(game.get("id", "")).strip() or uuid.uuid4().hex
    safe_platform = re.sub(r"[^a-z0-9]+", "_", platform).strip("_") or "game"
    return f"{safe_platform}_{identifier}"


def existing_downloaded_cover(key: str) -> str:
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = COVERS_DIR / f"{key}{suffix}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return str(candidate.resolve())
    return ""


def detected_image_suffix(data: bytes, content_type: str = "", url: str = "") -> str:
    content_type = content_type.casefold()
    if data.startswith(b"\xff\xd8\xff") or "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") or "png" in content_type:
        return ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" or "webp" in content_type:
        return ".webp"
    suffix = Path(url.split("?", 1)[0]).suffix.casefold()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ""


def save_cover_bytes(data: bytes, key: str, content_type: str = "", url: str = "") -> str:
    suffix = detected_image_suffix(data, content_type, url)
    if not suffix or not data:
        return ""
    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        destination = COVERS_DIR / f"{key}{suffix}"
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        return str(destination.resolve())
    except OSError:
        return ""


def copy_detected_cover(source: Path, key: str) -> str:
    if not source.is_file():
        return ""
    suffix = source.suffix.casefold()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        return ""
    try:
        COVERS_DIR.mkdir(parents=True, exist_ok=True)
        destination = COVERS_DIR / f"{key}{suffix}"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return str(destination.resolve())
    except OSError:
        return ""


def request_bytes(url: str, accept: str, data: bytes | None = None, content_type: str = "") -> tuple[bytes, str]:
    headers = {
        "User-Agent": COVER_USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.8",
    }
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=COVER_DOWNLOAD_TIMEOUT) as response:
            response_type = str(response.headers.get("Content-Type", ""))
            payload = response.read(MAX_COVER_DOWNLOAD_BYTES + 1)
            if len(payload) > MAX_COVER_DOWNLOAD_BYTES:
                return b"", ""
            return payload, response_type
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return b"", ""


def request_json(url: str, data: dict[str, Any] | None = None) -> Any:
    encoded = json.dumps(data).encode("utf-8") if data is not None else None
    payload, _ = request_bytes(
        url,
        "application/json, text/plain, */*",
        encoded,
        "application/json" if data is not None else "",
    )
    if not payload:
        return {}
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def find_local_steam_cover(steam_executable: str, app_id: str) -> Path | None:
    if not steam_executable or not app_id:
        return None
    cache = Path(steam_executable).parent / "appcache" / "librarycache"
    if not cache.is_dir():
        return None

    candidates = [
        cache / f"{app_id}_library_600x900.jpg",
        cache / f"{app_id}_library_600x900.png",
        cache / f"{app_id}_library_capsule.jpg",
        cache / f"{app_id}_library_capsule.png",
        cache / app_id / "library_600x900.jpg",
        cache / app_id / "library_600x900.png",
        cache / app_id / "library_capsule.jpg",
        cache / app_id / "library_capsule.png",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    app_folder = cache / app_id
    if app_folder.is_dir():
        for pattern in ("*library*600x900*", "*library*capsule*", "*portrait*", "*tall*"):
            for candidate in app_folder.glob(pattern):
                if candidate.is_file() and candidate.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}:
                    return candidate
    return None


def download_image_url(url: str, key: str) -> str:
    if not url:
        return ""
    payload, content_type = request_bytes(url, "image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
    return save_cover_bytes(payload, key, content_type, url) if payload else ""


def download_steam_cover(game: dict[str, Any], steam_executable: str) -> str:
    app_id = str(game.get("steam_app_id", "")).strip()
    if not app_id.isdigit():
        return ""
    key = cover_file_key(game)
    existing = existing_downloaded_cover(key)
    if existing:
        return existing

    local_cover = find_local_steam_cover(steam_executable, app_id)
    if local_cover:
        copied = copy_detected_cover(local_cover, key)
        if copied:
            return copied

    direct_urls = [
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg",
        f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg",
    ]
    for url in direct_urls:
        downloaded = download_image_url(url, key)
        if downloaded:
            return downloaded

    details = request_json(f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english")
    app_data = details.get(app_id, {}) if isinstance(details, dict) else {}
    data = app_data.get("data", {}) if isinstance(app_data, dict) and app_data.get("success") else {}
    if isinstance(data, dict):
        for field in ("header_image", "background_raw", "background"):
            downloaded = download_image_url(str(data.get(field, "")), key)
            if downloaded:
                return downloaded
    return ""


def epic_image_priority(image: dict[str, Any]) -> tuple[int, str]:
    image_type = str(image.get("type", "")).casefold()
    if any(token in image_type for token in ("tall", "portrait", "vertical")):
        priority = 0
    elif "thumbnail" in image_type:
        priority = 1
    elif "offerimage" in image_type or "dieselstorefront" in image_type:
        priority = 2
    elif any(token in image_type for token in ("wide", "landscape", "logo")):
        priority = 4
    else:
        priority = 3
    return priority, image_type


def epic_catalog_item(game: dict[str, Any]) -> dict[str, Any]:
    namespace = str(game.get("epic_namespace", "")).strip()
    catalog_item_id = str(game.get("epic_catalog_item_id", "")).strip()
    if not namespace or not catalog_item_id:
        return {}
    parameters = urlencode(
        {
            "id": catalog_item_id,
            "includeDLCDetails": "true",
            "includeMainGameDetails": "true",
            "country": "RS",
            "locale": "en-US",
        }
    )
    hosts = (
        "catalog-public-service-prod06.ol.epicgames.com",
        "catalog-public-service-prod.ol.epicgames.com",
    )
    for host in hosts:
        url = f"https://{host}/catalog/api/shared/namespace/{quote(namespace, safe='')}/bulk/items?{parameters}"
        result = request_json(url)
        if isinstance(result, dict):
            item = result.get(catalog_item_id)
            if isinstance(item, dict):
                return item
    return {}


def download_epic_cover(game: dict[str, Any]) -> str:
    key = cover_file_key(game)
    existing = existing_downloaded_cover(key)
    if existing:
        return existing
    item = epic_catalog_item(game)
    images = item.get("keyImages", []) if isinstance(item, dict) else []
    if not isinstance(images, list):
        return ""
    valid_images = [image for image in images if isinstance(image, dict) and str(image.get("url", "")).strip()]
    valid_images.sort(key=epic_image_priority)
    for image in valid_images:
        downloaded = download_image_url(str(image.get("url", "")).strip(), key)
        if downloaded:
            return downloaded
    return ""


def download_cover_for_game(game: dict[str, Any], steam_executable: str) -> str:
    current = str(game.get("cover", "")).strip()
    if current and Path(current).is_file():
        return current
    platform = str(game.get("platform", "")).strip().casefold()
    if platform == "steam":
        return download_steam_cover(game, steam_executable)
    if platform == "epic games":
        return download_epic_cover(game)
    return ""


def detect_steam_executable() -> str:
    candidates: list[Path] = []

    if winreg is not None:
        registry_locations = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]
        for hive, key_name, value_name in registry_locations:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, value_name)
                path = Path(normalize_path(str(value)))
                candidates.append(path if path.suffix.lower() == ".exe" else path / "steam.exe")
            except OSError:
                continue

    for environment_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        value = os.environ.get(environment_name)
        if value:
            candidates.append(Path(value) / "Steam" / "steam.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def tokenize_vdf(content: str) -> list[str]:
    pattern = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')
    tokens: list[str] = []
    for match in pattern.finditer(content):
        quoted, brace = match.groups()
        tokens.append(brace if brace else quoted.replace(r'\"', '"').replace('\\\\', '\\'))
    return tokens


def parse_vdf(content: str) -> dict[str, Any]:
    tokens = tokenize_vdf(content)

    def parse_object(index: int, stop_at_brace: bool = False) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                if stop_at_brace:
                    return result, index + 1
                index += 1
                continue
            if token == "{":
                index += 1
                continue
            key = token
            index += 1
            if index >= len(tokens):
                result[key] = ""
                break
            if tokens[index] == "{":
                value, index = parse_object(index + 1, True)
            else:
                value = tokens[index]
                index += 1
            result[key] = value
        return result, index

    parsed, _ = parse_object(0)
    return parsed


def read_saved_steam_accounts(steam_executable: str) -> list[dict[str, str]]:
    if not steam_executable:
        return []
    login_file = Path(steam_executable).parent / "config" / "loginusers.vdf"
    if not login_file.is_file():
        return []
    try:
        parsed = parse_vdf(login_file.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []

    users = parsed.get("users", {})
    if not isinstance(users, dict):
        return []

    accounts: list[dict[str, str]] = []
    for steam_id, data in users.items():
        if not isinstance(data, dict):
            continue
        account_name = str(data.get("AccountName", "")).strip()
        if not account_name:
            continue
        accounts.append(
            {
                "steam_id": str(steam_id),
                "account_name": account_name,
                "persona_name": str(data.get("PersonaName", account_name)).strip() or account_name,
                "most_recent": str(data.get("MostRecent", "0")),
                "remember_password": str(data.get("RememberPassword", "0")),
            }
        )

    accounts.sort(key=lambda item: (item.get("most_recent") != "1", item["persona_name"].casefold()))
    return accounts


def steam_library_folders(steam_executable: str) -> list[Path]:
    if not steam_executable:
        return []
    steam_root = Path(steam_executable).parent
    libraries: list[Path] = [steam_root]
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if library_file.is_file():
        try:
            parsed = parse_vdf(library_file.read_text(encoding="utf-8", errors="replace"))
            data = parsed.get("libraryfolders", parsed)
            if isinstance(data, dict):
                for key, value in data.items():
                    if not str(key).isdigit():
                        continue
                    raw_path = value.get("path", "") if isinstance(value, dict) else value
                    if raw_path:
                        libraries.append(Path(normalize_path(str(raw_path))))
        except OSError:
            pass

    unique: list[Path] = []
    seen: set[str] = set()
    for library in libraries:
        try:
            key = str(library.resolve()).casefold()
        except OSError:
            key = str(library).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(library)
    return unique


def scan_installed_steam_games(steam_executable: str) -> tuple[list[dict[str, Any]], list[str]]:
    games: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not steam_executable or not Path(steam_executable).is_file():
        return games, ["Steam was not detected. Configure steam.exe in Settings."]

    libraries = steam_library_folders(steam_executable)
    if not libraries:
        return games, ["No Steam library folders were detected."]

    seen_app_ids: set[str] = set()
    manifest_count = 0
    for library in libraries:
        steamapps = library / "steamapps"
        if not steamapps.is_dir():
            continue
        for manifest in steamapps.glob("appmanifest_*.acf"):
            manifest_count += 1
            try:
                parsed = parse_vdf(manifest.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            state = parsed.get("AppState", parsed)
            if not isinstance(state, dict):
                continue
            app_id = str(state.get("appid", "")).strip()
            name = str(state.get("name", "")).strip()
            install_dir_name = str(state.get("installdir", "")).strip()
            if not app_id.isdigit() or not name or app_id in seen_app_ids:
                continue
            if app_id == "228980" or name.casefold() == "steamworks common redistributables":
                continue

            install_location = steamapps / "common" / install_dir_name if install_dir_name else Path()
            if install_dir_name and not install_location.exists():
                continue
            record = default_game_record()
            record.update(
                {
                    "name": name,
                    "platform": "Steam",
                    "target": f"steam://rungameid/{app_id}",
                    "steam_app_id": app_id,
                    "steam_account": "",
                    "steam_mode": "current",
                    "source_id": f"steam:{app_id}",
                    "install_location": str(install_location) if install_dir_name else "",
                    "steam_library": str(library),
                    "imported": True,
                }
            )
            games.append(record)
            seen_app_ids.add(app_id)

    if manifest_count == 0:
        warnings.append("No Steam app manifests were found in the detected libraries.")
    games.sort(key=lambda item: str(item.get("name", "")).casefold())
    return games, warnings


def read_json_with_bom(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def epic_manifest_directories() -> list[Path]:
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    candidates = [program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"]
    for environment_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        program_files = os.environ.get(environment_name)
        if program_files:
            candidates.append(Path(program_files) / "Epic Games" / "Launcher" / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests")
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def build_epic_uri(namespace: str, catalog_item_id: str, app_name: str) -> str:
    if not app_name:
        return ""
    if namespace and catalog_item_id:
        artifact = quote(f"{namespace}:{catalog_item_id}:{app_name}", safe="")
    else:
        artifact = quote(app_name, safe="")
    return f"com.epicgames.launcher://apps/{artifact}?action=launch&silent=true"


def epic_record_from_manifest(data: dict[str, Any]) -> dict[str, Any] | None:
    if bool(data.get("bIsIncompleteInstall", False)):
        return None
    display_name = str(data.get("DisplayName", "")).strip()
    install_location = str(data.get("InstallLocation", "")).strip()
    launch_executable = str(data.get("LaunchExecutable", "")).strip()
    app_name = str(data.get("MainGameAppName") or data.get("AppName") or "").strip()
    catalog_item_id = str(data.get("MainGameCatalogItemId") or data.get("CatalogItemId") or "").strip()
    namespace = str(data.get("MainGameCatalogNamespace") or data.get("CatalogNamespace") or data.get("Namespace") or "").strip()
    if not display_name or not app_name:
        return None
    if install_location and not Path(normalize_path(install_location)).exists():
        return None

    uri = build_epic_uri(namespace, catalog_item_id, app_name)
    if not uri:
        return None
    source_parts = [namespace, catalog_item_id, app_name]
    source_id = "epic:" + ":".join(part.casefold() for part in source_parts if part)
    executable_path = ""
    if install_location and launch_executable:
        executable_path = str(Path(normalize_path(install_location)) / launch_executable)

    record = default_game_record()
    record.update(
        {
            "name": display_name,
            "platform": "Epic Games",
            "target": uri,
            "source_id": source_id,
            "install_location": normalize_path(install_location) if install_location else "",
            "epic_app_name": app_name,
            "epic_namespace": namespace,
            "epic_catalog_item_id": catalog_item_id,
            "epic_launch_executable": executable_path,
            "imported": True,
        }
    )
    return record


def epic_launcher_installed_files() -> list[Path]:
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    candidates = [program_data / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"]
    for environment_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        program_files = os.environ.get(environment_name)
        if program_files:
            candidates.append(Path(program_files) / "Epic Games" / "Launcher" / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat")
    return candidates


def scan_epic_launcher_installed_file() -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for installed_file in epic_launcher_installed_files():
        data = read_json_with_bom(installed_file, {})
        installations = data.get("InstallationList", []) if isinstance(data, dict) else []
        if not isinstance(installations, list):
            continue
        for item in installations:
            if not isinstance(item, dict):
                continue
            display_name = str(item.get("AppName") or item.get("ArtifactId") or "").strip()
            artifact_id = str(item.get("ArtifactId") or item.get("AppName") or "").strip()
            install_location = str(item.get("InstallLocation", "")).strip()
            namespace = str(item.get("NamespaceId", "")).strip()
            catalog_item_id = str(item.get("ItemId", "")).strip()
            if not artifact_id or (install_location and not Path(normalize_path(install_location)).exists()):
                continue
            record = default_game_record()
            record.update(
                {
                    "name": display_name or artifact_id,
                    "platform": "Epic Games",
                    "target": build_epic_uri(namespace, catalog_item_id, artifact_id),
                    "source_id": "epic:" + ":".join(part.casefold() for part in (namespace, catalog_item_id, artifact_id) if part),
                    "install_location": normalize_path(install_location) if install_location else "",
                    "epic_app_name": artifact_id,
                    "epic_namespace": namespace,
                    "epic_catalog_item_id": catalog_item_id,
                    "imported": True,
                }
            )
            games.append(record)
    return games


def scan_installed_epic_games() -> tuple[list[dict[str, Any]], list[str]]:
    games_by_id: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    found_manifest_directory = False

    for manifest_directory in epic_manifest_directories():
        if not manifest_directory.is_dir():
            continue
        found_manifest_directory = True
        for manifest in manifest_directory.glob("*.item"):
            data = read_json_with_bom(manifest, {})
            if not isinstance(data, dict):
                continue
            record = epic_record_from_manifest(data)
            if record:
                games_by_id.setdefault(str(record.get("source_id", "")), record)

    for record in scan_epic_launcher_installed_file():
        games_by_id.setdefault(str(record.get("source_id", "")), record)

    if not found_manifest_directory and not games_by_id:
        warnings.append("Epic Games Launcher manifests were not found.")
    games = sorted(games_by_id.values(), key=lambda item: str(item.get("name", "")).casefold())
    return games, warnings



def _registry_value(key: Any, name: str, default: str = "") -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return str(value).strip()
    except OSError:
        return default


def _clean_display_icon(value: str) -> str:
    value = value.strip().strip('"')
    if not value:
        return ""
    # Uninstall entries often append an icon index, e.g. game.exe,0.
    value = re.sub(r",-?\d+$", "", value).strip().strip('"')
    return normalize_path(value)


def _find_executable(install_location: str, display_icon: str = "") -> str:
    icon_path = Path(_clean_display_icon(display_icon)) if display_icon else Path()
    if icon_path.is_file() and icon_path.suffix.lower() == ".exe":
        return str(icon_path)
    if not install_location:
        return ""
    root = Path(normalize_path(install_location))
    if not root.is_dir():
        return ""
    excluded = {"unins000.exe", "uninstall.exe", "unitycrashhandler64.exe", "unitycrashhandler32.exe"}
    try:
        candidates = [
            path for path in root.glob("*.exe")
            if path.name.casefold() not in excluded and "unins" not in path.name.casefold()
        ]
        if not candidates:
            candidates = [
                path for path in root.rglob("*.exe")
                if len(path.relative_to(root).parts) <= 3
                and path.name.casefold() not in excluded
                and "unins" not in path.name.casefold()
            ]
        if candidates:
            candidates.sort(key=lambda path: ("launcher" in path.name.casefold(), len(path.name), str(path).casefold()))
            return str(candidates[0])
    except OSError:
        pass
    return ""


def scan_gog_games() -> tuple[list[dict[str, Any]], list[str]]:
    games: list[dict[str, Any]] = []
    warnings: list[str] = []
    if winreg is None:
        return games, ["GOG scanning is available on Windows only."]

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\GOG.com\Games"),
    ]
    seen: set[str] = set()
    found_root = False
    for hive, root_name in roots:
        try:
            with winreg.OpenKey(hive, root_name) as root:
                found_root = True
                index = 0
                while True:
                    try:
                        game_id = winreg.EnumKey(root, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, game_id) as key:
                            name = _registry_value(key, "gameName") or _registry_value(key, "GAMENAME")
                            install_location = _registry_value(key, "path") or _registry_value(key, "PATH")
                            executable = _registry_value(key, "exe") or _registry_value(key, "EXE")
                            if executable and install_location and not Path(executable).is_absolute():
                                executable = str(Path(normalize_path(install_location)) / executable)
                            executable = normalize_path(executable) if executable else _find_executable(install_location)
                            if not name or not executable or not Path(executable).is_file():
                                continue
                            identity = f"gog:{game_id}".casefold()
                            if identity in seen:
                                continue
                            record = default_game_record()
                            record.update({
                                "name": name,
                                "platform": "GOG Galaxy",
                                "target": executable,
                                "source_id": identity,
                                "install_location": normalize_path(install_location) if install_location else str(Path(executable).parent),
                                "imported": True,
                            })
                            games.append(record)
                            seen.add(identity)
                    except OSError:
                        continue
        except OSError:
            continue
    if not found_root:
        warnings.append("No installed GOG games were detected in the Windows registry.")
    games.sort(key=lambda item: str(item.get("name", "")).casefold())
    return games, warnings


def _scan_uninstall_registry_for_ea() -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    if winreg is None:
        return games
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    seen: set[str] = set()
    for hive, root_name in roots:
        try:
            with winreg.OpenKey(hive, root_name) as root:
                index = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(root, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, sub_name) as key:
                            name = _registry_value(key, "DisplayName")
                            publisher = _registry_value(key, "Publisher").casefold()
                            if not name or not any(token in publisher for token in ("electronic arts", "ea swiss", "ea games")):
                                continue
                            lower_name = name.casefold()
                            if any(token in lower_name for token in ("ea app", "origin", "web helper", "anticheat")):
                                continue
                            install_location = _registry_value(key, "InstallLocation")
                            display_icon = _registry_value(key, "DisplayIcon")
                            executable = _find_executable(install_location, display_icon)
                            if not executable:
                                continue
                            identity = f"ea:{normalize_path(executable).casefold()}"
                            if identity in seen:
                                continue
                            record = default_game_record()
                            record.update({
                                "name": name,
                                "platform": "EA App",
                                "target": executable,
                                "source_id": identity,
                                "install_location": normalize_path(install_location) if install_location else str(Path(executable).parent),
                                "imported": True,
                            })
                            games.append(record)
                            seen.add(identity)
                    except OSError:
                        continue
        except OSError:
            continue
    return games


def scan_ea_games() -> tuple[list[dict[str, Any]], list[str]]:
    games = _scan_uninstall_registry_for_ea()
    warnings = [] if games else ["No installed EA App or legacy Origin games were detected."]
    games.sort(key=lambda item: str(item.get("name", "")).casefold())
    return games, warnings


def launcher_detection_summary(steam_executable: str) -> dict[str, bool]:
    steam = bool(steam_executable and Path(steam_executable).is_file())
    epic = any(path.is_dir() for path in epic_manifest_directories()) or any(path.is_file() for path in epic_launcher_installed_files())
    gog_games, _ = scan_gog_games()
    ea_games, _ = scan_ea_games()
    return {"Steam": steam, "Epic Games": epic, "GOG Galaxy": bool(gog_games), "EA App / Origin": bool(ea_games)}

def normalized_target(record: dict[str, Any]) -> str:
    value = str(record.get("target", "")).strip()
    if not value:
        return ""
    if "://" in value:
        return value.casefold()
    return normalize_path(value).casefold()


def game_identity(record: dict[str, Any]) -> str:
    platform = str(record.get("platform", "")).casefold()
    if platform == "steam":
        app_id = str(record.get("steam_app_id", "")).strip()
        if not app_id:
            match = re.search(r"rungameid/(\d+)", str(record.get("target", "")), flags=re.IGNORECASE)
            app_id = match.group(1) if match else ""
        if app_id:
            return f"steam:{app_id}"
    source_id = str(record.get("source_id", "")).strip().casefold()
    if source_id:
        return source_id
    target = normalized_target(record)
    return f"{platform}:{target}" if target else f"{platform}:name:{str(record.get('name', '')).casefold()}"


def games_are_duplicates(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if game_identity(first) == game_identity(second):
        return True
    first_platform = str(first.get("platform", "")).casefold()
    second_platform = str(second.get("platform", "")).casefold()
    if first_platform != second_platform:
        return False
    if normalized_target(first) and normalized_target(first) == normalized_target(second):
        return True
    if first_platform == "epic games":
        first_name = str(first.get("name", "")).strip().casefold()
        second_name = str(second.get("name", "")).strip().casefold()
        if first_name and first_name == second_name:
            return True
        first_executable = str(first.get("epic_launch_executable", "")).strip()
        second_executable = str(second.get("epic_launch_executable", "")).strip()
        if first_executable and second_executable:
            return normalize_path(first_executable).casefold() == normalize_path(second_executable).casefold()
    return False


def steam_is_running() -> bool:
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "steam.exe" in completed.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def default_game_record() -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "name": "",
        "platform": "Local",
        "target": "",
        "cover": "",
        "favorite": False,
        "last_played": "",
        "steam_app_id": "",
        "steam_account": "",
        "steam_mode": "current",
        "source_id": "",
        "install_location": "",
        "steam_library": "",
        "epic_app_name": "",
        "epic_namespace": "",
        "epic_catalog_item_id": "",
        "epic_launch_executable": "",
        "imported": False,
    }


def migrate_game_record(record: dict[str, Any]) -> dict[str, Any]:
    migrated = default_game_record()
    migrated.update(record)
    target = str(migrated.get("target", ""))
    if "platform" not in record:
        if target.lower().startswith("steam://"):
            migrated["platform"] = "Steam"
        elif target.lower().startswith(("ea://", "link2ea://")):
            migrated["platform"] = "EA App"
        else:
            migrated["platform"] = "Local"
    if migrated["platform"] == "Steam" and not migrated.get("steam_app_id"):
        match = re.search(r"rungameid/(\d+)", target)
        if match:
            migrated["steam_app_id"] = match.group(1)
    if migrated["platform"] == "Steam" and migrated.get("steam_app_id") and not migrated.get("source_id"):
        migrated["source_id"] = f"steam:{migrated['steam_app_id']}"
    if migrated["platform"] == "Epic Games" and not migrated.get("source_id"):
        epic_parts = [
            str(migrated.get("epic_namespace", "")),
            str(migrated.get("epic_catalog_item_id", "")),
            str(migrated.get("epic_app_name", "")),
        ]
        if any(epic_parts):
            migrated["source_id"] = "epic:" + ":".join(part.casefold() for part in epic_parts if part)
    cover_value = str(migrated.get("cover", "")).strip()
    if cover_value:
        cover_path = Path(cover_value)
        migrated_cover = COVERS_DIR / cover_path.name
        if path_is_within(cover_path, LEGACY_COVERS_DIR) and migrated_cover.exists():
            migrated["cover"] = str(migrated_cover)
    migrated["favorite"] = bool(migrated.get("favorite", False))
    migrated["imported"] = bool(migrated.get("imported", False))
    return migrated


def placeholder_cover(name: str) -> QPixmap:
    pixmap = QPixmap(COVER_WIDTH, COVER_HEIGHT)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, COVER_WIDTH, COVER_HEIGHT)
    gradient.setColorAt(0.0, QColor("#27455e"))
    gradient.setColorAt(0.55, QColor("#172b3d"))
    gradient.setColorAt(1.0, QColor("#0d151e"))
    path = QPainterPath()
    path.addRoundedRect(QRect(0, 0, COVER_WIDTH, COVER_HEIGHT), 9, 9)
    painter.fillPath(path, gradient)
    initials = "".join(word[0] for word in name.split()[:3] if word).upper() or "GAME"
    painter.setPen(QColor("#65bff1"))
    painter.setFont(QFont("Segoe UI", 27, QFont.Weight.Bold))
    painter.drawText(QRect(10, 10, COVER_WIDTH - 20, COVER_HEIGHT - 20), Qt.AlignmentFlag.AlignCenter, initials)
    painter.setPen(QColor("#8f98a0"))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(QRect(10, COVER_HEIGHT - 36, COVER_WIDTH - 20, 22), Qt.AlignmentFlag.AlignCenter, "NO COVER")
    painter.end()
    return pixmap


def cover_pixmap(path_value: str, name: str) -> QPixmap:
    if path_value and Path(path_value).is_file():
        pixmap = QPixmap(path_value)
        if not pixmap.isNull():
            return pixmap.scaled(
                COVER_WIDTH,
                COVER_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
    return placeholder_cover(name)


class UpdateCheckWorker(QThread):
    result_ready = Signal(object)

    def run(self) -> None:
        try:
            information = latest_release_information()
            latest_version = str(information.get("latest_version", ""))
            information["status"] = "available" if is_newer_version(latest_version) else "up_to_date"
            self.result_ready.emit(information)
        except RuntimeError as error:
            self.result_ready.emit({"status": "error", "message": str(error)})
        except Exception as error:
            self.result_ready.emit({"status": "error", "message": f"Unexpected update error: {error}"})


class UpdateDownloadWorker(QThread):
    progress_changed = Signal(int, int)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, asset: dict[str, Any], version: str) -> None:
        super().__init__()
        self.asset = dict(asset)
        self.version = version

    def run(self) -> None:
        source_url = str(self.asset.get("browser_download_url", "")).strip()
        if not source_url.startswith("https://"):
            self.failed.emit("The release does not contain a valid HTTPS download URL.")
            return

        expected_size = int(self.asset.get("size", 0) or 0)
        if expected_size > MAX_UPDATE_DOWNLOAD_BYTES:
            self.failed.emit("The update file is larger than the allowed download limit.")
            return

        safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", self.version.strip()) or "latest"
        destination = UPDATE_DIR / f"V_Game_Launcher-{safe_version}.exe"
        partial = destination.with_suffix(destination.suffix + ".part")
        digest_value = str(self.asset.get("digest", "")).strip().casefold()
        expected_sha256 = digest_value.removeprefix("sha256:") if digest_value.startswith("sha256:") else ""
        hasher = hashlib.sha256()

        try:
            UPDATE_DIR.mkdir(parents=True, exist_ok=True)
            partial.unlink(missing_ok=True)
            request = update_download_request(source_url)
            with urlopen(request, timeout=UPDATE_DOWNLOAD_TIMEOUT) as response, partial.open("wb") as file:
                header_size = int(response.headers.get("Content-Length", "0") or 0)
                total_size = expected_size or header_size
                downloaded = 0
                while True:
                    if self.isInterruptionRequested():
                        raise InterruptedError
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_UPDATE_DOWNLOAD_BYTES:
                        raise RuntimeError("The update exceeded the allowed download limit.")
                    file.write(chunk)
                    hasher.update(chunk)
                    self.progress_changed.emit(downloaded, total_size)

            actual_size = partial.stat().st_size
            if expected_size and actual_size != expected_size:
                raise RuntimeError("The downloaded update size does not match the GitHub release asset.")
            if expected_sha256 and hasher.hexdigest().casefold() != expected_sha256:
                raise RuntimeError("The downloaded update failed the SHA-256 integrity check.")
            if actual_size == 0:
                raise RuntimeError("The downloaded update file is empty.")
            with partial.open("rb") as downloaded_file:
                if downloaded_file.read(2) != b"MZ":
                    raise RuntimeError("The downloaded file is not a valid Windows executable.")

            destination.unlink(missing_ok=True)
            partial.replace(destination)
            self.completed.emit(str(destination))
        except InterruptedError:
            partial.unlink(missing_ok=True)
            self.cancelled.emit()
        except HTTPError as error:
            partial.unlink(missing_ok=True)
            self.failed.emit(f"GitHub returned HTTP {error.code} while downloading the update.")
        except (URLError, TimeoutError, OSError, RuntimeError, ValueError) as error:
            partial.unlink(missing_ok=True)
            self.failed.emit(str(error))


class CoverDownloadWorker(QThread):
    progress_changed = Signal(str)
    cover_downloaded = Signal(str, str)
    completed = Signal(int, int)

    def __init__(self, games: list[dict[str, Any]], steam_executable: str) -> None:
        super().__init__()
        self.games = [dict(game) for game in games]
        self.steam_executable = steam_executable

    def run(self) -> None:
        downloaded_count = 0
        total = len(self.games)
        for index, game in enumerate(self.games, start=1):
            if self.isInterruptionRequested():
                break
            name = str(game.get("name", "Game"))
            self.progress_changed.emit(f"Downloading covers {index}/{total}: {name}")
            cover = download_cover_for_game(game, self.steam_executable)
            if cover:
                game_id = str(game.get("id", ""))
                if game_id:
                    self.cover_downloaded.emit(game_id, cover)
                    downloaded_count += 1
        self.completed.emit(downloaded_count, total)


class SteamLaunchWorker(QThread):
    status_changed = Signal(str)
    launch_succeeded = Signal()
    launch_failed = Signal(str)

    def __init__(self, steam_executable: str, app_id: str, account_name: str, mode: str, restart_steam: bool) -> None:
        super().__init__()
        self.steam_executable = steam_executable
        self.app_id = app_id
        self.account_name = account_name
        self.mode = mode
        self.restart_steam = restart_steam

    def run(self) -> None:
        try:
            steam_path = Path(self.steam_executable)
            if not steam_path.is_file():
                raise FileNotFoundError("Steam.exe was not found.")

            if self.restart_steam and steam_is_running():
                self.status_changed.emit("Closing Steam…")
                subprocess.run(
                    [str(steam_path), "-shutdown"],
                    cwd=str(steam_path.parent),
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                deadline = time.monotonic() + 20
                while steam_is_running() and time.monotonic() < deadline:
                    if self.isInterruptionRequested():
                        return
                    time.sleep(0.5)
                if steam_is_running():
                    raise RuntimeError("Steam did not close in time. Close it manually and try again.")

            if self.restart_steam or not steam_is_running():
                arguments = [str(steam_path)]
                if self.account_name:
                    arguments.extend(["-login", self.account_name])
                if self.mode == "offline":
                    arguments.append("-offlinemode")
                self.status_changed.emit("Starting Steam…")
                subprocess.Popen(
                    arguments,
                    cwd=str(steam_path.parent),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for _ in range(16):
                    if self.isInterruptionRequested():
                        return
                    time.sleep(0.5)

            self.status_changed.emit("Launching game…")
            os.startfile(f"steam://rungameid/{self.app_id}")
            self.launch_succeeded.emit()
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.launch_failed.emit(str(error))


class SidebarButton(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(42)
        self.setProperty("sidebarButton", True)


class GameCard(QFrame):
    launch_requested = Signal(dict)
    edit_requested = Signal(dict)
    remove_requested = Signal(dict)
    favorite_requested = Signal(dict)

    def __init__(self, game: dict[str, Any], running: bool = False, launching: bool = False, blocked: bool = False) -> None:
        super().__init__()
        self.game = game
        self.running = running
        self.launching = launching
        self.blocked = blocked
        self.setObjectName("runningGameCard" if running else "gameCard")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        cover_frame = QFrame()
        cover_frame.setObjectName("coverContainer")
        cover_frame.setFixedSize(COVER_WIDTH, COVER_HEIGHT)
        cover_layout = QVBoxLayout(cover_frame)
        cover_layout.setContentsMargins(0, 0, 0, 0)

        image = QLabel()
        image.setFixedSize(COVER_WIDTH, COVER_HEIGHT)
        image.setPixmap(cover_pixmap(str(game.get("cover", "")), str(game.get("name", "Game"))))
        image.setScaledContents(True)
        cover_layout.addWidget(image)

        favorite = QToolButton(cover_frame)
        favorite.setText("★" if game.get("favorite") else "☆")
        favorite.setObjectName("favoriteButton")
        favorite.setGeometry(COVER_WIDTH - 40, 8, 32, 32)
        favorite.clicked.connect(lambda: self.favorite_requested.emit(self.game))

        if self.running:
            running_badge = QLabel("● RUNNING", cover_frame)
            running_badge.setObjectName("runningBadge")
            running_badge.adjustSize()
            running_badge.move(8, 10)

        layout.addWidget(cover_frame)

        title = QLabel(str(game.get("name", "Unnamed Game")))
        title.setObjectName("gameTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(44)
        layout.addWidget(title)

        platform = QLabel(str(game.get("platform", "Local")))
        platform.setObjectName("platformLabel")
        layout.addWidget(platform)
        layout.addStretch(1)

        if self.running:
            play = QPushButton("RUNNING")
            play.setObjectName("runningButton")
            play.setEnabled(False)
        elif self.launching:
            play = QPushButton("STARTING…")
            play.setObjectName("startingButton")
            play.setEnabled(False)
        elif self.blocked:
            play = QPushButton("PLAY")
            play.setObjectName("blockedPlayButton")
            play.setEnabled(False)
            play.setToolTip("Close the currently running game before launching another one.")
        else:
            play = QPushButton("PLAY")
            play.setObjectName("playButton")
            play.clicked.connect(lambda: self.launch_requested.emit(self.game))
        layout.addWidget(play)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not (self.running or self.launching or self.blocked):
            self.launch_requested.emit(self.game)
        super().mouseDoubleClickEvent(event)

    def show_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        play_action = menu.addAction("Play")
        play_action.setEnabled(not (self.running or self.launching or self.blocked))
        edit_action = menu.addAction("Edit game")
        favorite_action = menu.addAction("Remove from favorites" if self.game.get("favorite") else "Add to favorites")
        menu.addSeparator()
        remove_action = menu.addAction("Remove from launcher")
        selected = menu.exec(self.mapToGlobal(position))
        if selected == play_action:
            self.launch_requested.emit(self.game)
        elif selected == edit_action:
            self.edit_requested.emit(self.game)
        elif selected == favorite_action:
            self.favorite_requested.emit(self.game)
        elif selected == remove_action:
            self.remove_requested.emit(self.game)


class GameDialog(QDialog):
    def __init__(self, steam_accounts: list[dict[str, str]], game: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Game" if game else "Add Game")
        self.setMinimumWidth(570)
        self.game = dict(game) if game else default_game_record()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)

        self.name_input = QLineEdit(str(self.game.get("name", "")))
        self.name_input.setPlaceholderText("Example: EA SPORTS FC 24")
        form.addRow("Game name", self.name_input)

        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["Local", "Steam", "EA App", "Epic Games", "Ubisoft Connect", "Custom URI"])
        self.platform_combo.setCurrentText(str(self.game.get("platform", "Local")))
        form.addRow("Platform", self.platform_combo)

        target_row = QHBoxLayout()
        self.target_input = QLineEdit(str(self.game.get("target", "")))
        self.target_input.setPlaceholderText("Executable path or launch URI")
        browse_target = QPushButton("Browse…")
        browse_target.clicked.connect(self.browse_target)
        target_row.addWidget(self.target_input, 1)
        target_row.addWidget(browse_target)
        form.addRow("Executable / URI", target_row)

        cover_row = QHBoxLayout()
        self.cover_input = QLineEdit(str(self.game.get("cover", "")))
        self.cover_input.setPlaceholderText("Optional cover image")
        browse_cover = QPushButton("Browse…")
        browse_cover.clicked.connect(self.browse_cover)
        cover_row.addWidget(self.cover_input, 1)
        cover_row.addWidget(browse_cover)
        form.addRow("Cover image", cover_row)

        self.app_id_input = QLineEdit(str(self.game.get("steam_app_id", "")))
        self.app_id_input.setPlaceholderText("Example: 2195250")
        self.app_id_input.textChanged.connect(self.update_steam_target)
        form.addRow("Steam App ID", self.app_id_input)

        self.account_combo = QComboBox()
        self.account_combo.addItem("Use current Steam account", "")
        for account in steam_accounts:
            label = f"{account['persona_name']} ({account['account_name']})"
            if account.get("most_recent") == "1":
                label += " — last used"
            self.account_combo.addItem(label, account["account_name"])
        self.account_combo.setCurrentIndex(max(0, self.account_combo.findData(str(self.game.get("steam_account", "")))))
        form.addRow("Steam account", self.account_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Use current Steam mode", "current")
        self.mode_combo.addItem("Online / normal launch", "online")
        self.mode_combo.addItem("Offline mode", "offline")
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(str(self.game.get("steam_mode", "current")))))
        form.addRow("Steam mode", self.mode_combo)

        self.favorite_checkbox = QCheckBox("Add to Favorites")
        self.favorite_checkbox.setChecked(bool(self.game.get("favorite", False)))
        form.addRow("", self.favorite_checkbox)

        self.steam_note = QLabel(
            "The launcher never stores Steam passwords or Steam Guard codes. Steam may still ask you to confirm the selected account."
        )
        self.steam_note.setWordWrap(True)
        self.steam_note.setObjectName("dialogNote")
        form.addRow("", self.steam_note)

        self.steam_rows = [self.app_id_input, self.account_combo, self.mode_combo, self.steam_note]
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.form = form
        self.platform_combo.currentTextChanged.connect(self.update_platform_fields)
        self.update_platform_fields(self.platform_combo.currentText())

    def update_platform_fields(self, platform: str) -> None:
        is_steam = platform == "Steam"
        for field in self.steam_rows:
            field.setVisible(is_steam)
            label = self.form.labelForField(field)
            if label:
                label.setVisible(is_steam)
        self.target_input.setReadOnly(is_steam)
        if is_steam:
            self.update_steam_target()

    def update_steam_target(self) -> None:
        if self.platform_combo.currentText() == "Steam":
            app_id = self.app_id_input.text().strip()
            self.target_input.setText(f"steam://rungameid/{app_id}" if app_id else "")

    def browse_target(self) -> None:
        if self.platform_combo.currentText() == "Steam":
            QMessageBox.information(self, "Steam game", "Enter the Steam App ID. The URI is created automatically.")
            return
        selected, _ = QFileDialog.getOpenFileName(self, "Select game executable", "", "Executable files (*.exe);;All files (*.*)")
        if selected:
            self.target_input.setText(selected)

    def browse_cover(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Select cover image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if selected:
            self.cover_input.setText(selected)

    def validate_and_accept(self) -> None:
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Missing name", "Enter the game name.")
            return
        if self.platform_combo.currentText() == "Steam":
            if not self.app_id_input.text().strip().isdigit():
                QMessageBox.warning(self, "Invalid Steam App ID", "Steam App ID must contain numbers only.")
                return
        elif not self.target_input.text().strip():
            QMessageBox.warning(self, "Missing target", "Select an executable or enter a launch URI.")
            return
        self.accept()

    def result_game(self) -> dict[str, Any]:
        result = dict(self.game)
        old_cover = str(result.get("cover", ""))
        selected_cover = self.cover_input.text().strip()
        if selected_cover and selected_cover != old_cover:
            selected_cover = copy_cover_to_library(selected_cover)
        platform = self.platform_combo.currentText()
        steam_app_id = self.app_id_input.text().strip()
        result.update(
            {
                "name": self.name_input.text().strip(),
                "platform": platform,
                "target": self.target_input.text().strip(),
                "cover": selected_cover,
                "favorite": self.favorite_checkbox.isChecked(),
                "steam_app_id": steam_app_id,
                "steam_account": str(self.account_combo.currentData() or ""),
                "steam_mode": str(self.mode_combo.currentData() or "current"),
            }
        )
        if platform == "Steam":
            result["source_id"] = f"steam:{steam_app_id}" if steam_app_id else ""
            result["epic_app_name"] = ""
            result["epic_namespace"] = ""
            result["epic_catalog_item_id"] = ""
            result["epic_launch_executable"] = ""
        elif platform == "Epic Games":
            if not str(result.get("source_id", "")).casefold().startswith("epic:"):
                result["source_id"] = ""
            result["steam_app_id"] = ""
            result["steam_account"] = ""
            result["steam_mode"] = "current"
        else:
            result["source_id"] = ""
            result["install_location"] = ""
            result["steam_library"] = ""
            result["steam_app_id"] = ""
            result["steam_account"] = ""
            result["steam_mode"] = "current"
            result["epic_app_name"] = ""
            result["epic_namespace"] = ""
            result["epic_catalog_item_id"] = ""
            result["epic_launch_executable"] = ""
            result["imported"] = False
        return migrate_game_record(result)


class SettingsDialog(QDialog):
    settings_saved = Signal(dict)

    def __init__(self, settings: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumSize(700, 500)
        self.settings = dict(settings)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        general_tab = QWidget()
        general = QVBoxLayout(general_tab)
        general_title = QLabel("General")
        general_title.setObjectName("sectionTitle")
        general.addWidget(general_title)
        self.start_maximized = QCheckBox("Start maximized")
        self.start_maximized.setChecked(bool(settings.get("start_maximized", False)))
        self.remember_window = QCheckBox("Remember window size and position")
        self.remember_window.setChecked(bool(settings.get("remember_window", True)))
        self.automatic_updates = QCheckBox("Automatically check for updates")
        self.automatic_updates.setChecked(bool(settings.get("automatic_updates", True)))
        general.addWidget(self.start_maximized)
        general.addWidget(self.remember_window)
        general.addWidget(self.automatic_updates)
        general.addSpacing(18)
        storage = QLabel(f"Library data folder:\n{DATA_DIR}")
        storage.setObjectName("settingsPanel")
        storage.setWordWrap(True)
        storage.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        general.addWidget(storage)
        open_folder = QPushButton("Open Folder")
        open_folder.clicked.connect(self.open_library_folder)
        general.addWidget(open_folder, 0, Qt.AlignmentFlag.AlignLeft)
        general.addStretch(1)
        tabs.addTab(general_tab, "General")

        launchers_tab = QWidget()
        launchers = QVBoxLayout(launchers_tab)
        steam_title = QLabel("Steam executable")
        steam_title.setObjectName("sectionTitle")
        launchers.addWidget(steam_title)
        path_row = QHBoxLayout()
        self.path_input = QLineEdit(str(settings.get("steam_executable", "")))
        self.path_input.setPlaceholderText("Path to steam.exe")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_steam)
        detect = QPushButton("Detect")
        detect.clicked.connect(self.detect_steam)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(browse)
        path_row.addWidget(detect)
        launchers.addLayout(path_row)

        detected_title = QLabel("Launcher detection")
        detected_title.setObjectName("sectionTitle")
        launchers.addWidget(detected_title)
        self.launcher_status = QLabel()
        self.launcher_status.setObjectName("settingsPanel")
        self.launcher_status.setWordWrap(True)
        launchers.addWidget(self.launcher_status)
        rescan = QPushButton("Rescan Launchers")
        rescan.clicked.connect(self.refresh_launcher_status)
        launchers.addWidget(rescan, 0, Qt.AlignmentFlag.AlignLeft)
        note = QLabel(
            "Epic Games is detected from its local manifests. GOG and EA/Origin games are detected from Windows registry entries. "
            "A manual launcher path is only required for Steam."
        )
        note.setObjectName("dialogNote")
        note.setWordWrap(True)
        launchers.addWidget(note)
        launchers.addStretch(1)
        tabs.addTab(launchers_tab, "Launchers")

        appearance_tab = QWidget()
        appearance = QVBoxLayout(appearance_tab)
        appearance_title = QLabel("Appearance")
        appearance_title.setObjectName("sectionTitle")
        appearance.addWidget(appearance_title)
        appearance.addWidget(QLabel("Choose the visual theme used by the launcher."))
        theme_row = QHBoxLayout()
        theme_label = QLabel("Theme")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        current_theme = str(settings.get("theme", "dark"))
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(current_theme)))
        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.theme_combo, 1)
        appearance.addLayout(theme_row)
        theme_note = QLabel("The selected theme is applied after saving Preferences.")
        theme_note.setObjectName("dialogNote")
        theme_note.setWordWrap(True)
        appearance.addWidget(theme_note)
        appearance.addStretch(1)
        tabs.addTab(appearance_tab, "Appearance")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_launcher_status()

    def browse_steam(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Select steam.exe", self.path_input.text(), "Steam executable (steam.exe);;Executable files (*.exe)")
        if selected:
            self.path_input.setText(selected)
            self.refresh_launcher_status()

    def detect_steam(self) -> None:
        detected = detect_steam_executable()
        if detected:
            self.path_input.setText(detected)
            self.refresh_launcher_status()
        else:
            QMessageBox.warning(self, "Steam not found", "Steam was not detected automatically. Select steam.exe manually.")

    def refresh_launcher_status(self) -> None:
        statuses = launcher_detection_summary(self.path_input.text().strip())
        lines = [f"{'✓' if detected else '✕'}  {name}: {'Detected' if detected else 'Not detected'}" for name, detected in statuses.items()]
        self.launcher_status.setText("\n".join(lines))

    def open_library_folder(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(DATA_DIR))
        except OSError as error:
            QMessageBox.warning(self, "Open folder", f"The library folder could not be opened:\n{error}")

    def save(self) -> None:
        steam_path = normalize_path(self.path_input.text())
        if steam_path and not Path(steam_path).is_file():
            QMessageBox.warning(self, "Invalid Steam path", "The selected steam.exe file does not exist.")
            return
        self.settings["steam_executable"] = steam_path
        self.settings["start_maximized"] = self.start_maximized.isChecked()
        self.settings["remember_window"] = self.remember_window.isChecked()
        self.settings["automatic_updates"] = self.automatic_updates.isChecked()
        self.settings["theme"] = str(self.theme_combo.currentData() or "dark")
        self.settings_saved.emit(self.settings)
        self.accept()


class ImportGamesDialog(QDialog):
    def __init__(
        self,
        steam_executable: str,
        existing_games: list[dict[str, Any]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Installed Games")
        self.setMinimumSize(900, 560)
        self.steam_executable = steam_executable
        self.existing_games = existing_games
        self.candidates: list[dict[str, Any]] = []

        layout = QVBoxLayout(self)
        title = QLabel("Import installed games")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        explanation = QLabel(
            "Steam and Epic games are read from their local manifests. GOG and EA/Origin games are detected from Windows registry entries. "
            "Each installed game appears once and can be reviewed before import."
        )
        explanation.setObjectName("dialogNote")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        scan_row = QHBoxLayout()
        self.scan_steam_button = QPushButton("Scan Steam")
        self.scan_epic_button = QPushButton("Scan Epic Games")
        self.scan_ea_button = QPushButton("Scan EA / Origin")
        self.scan_gog_button = QPushButton("Scan GOG")
        self.scan_all_button = QPushButton("Scan All")
        self.scan_steam_button.clicked.connect(self.scan_steam)
        self.scan_epic_button.clicked.connect(self.scan_epic)
        self.scan_ea_button.clicked.connect(self.scan_ea)
        self.scan_gog_button.clicked.connect(self.scan_gog)
        self.scan_all_button.clicked.connect(self.scan_all)
        scan_row.addWidget(self.scan_steam_button)
        scan_row.addWidget(self.scan_epic_button)
        scan_row.addWidget(self.scan_ea_button)
        scan_row.addWidget(self.scan_gog_button)
        scan_row.addWidget(self.scan_all_button)
        scan_row.addStretch(1)
        layout.addLayout(scan_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Import", "Game", "Platform", "Installed location", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self.update_import_button)
        layout.addWidget(self.table, 1)

        self.scan_status = QLabel("Ready to scan installed game libraries.")
        self.scan_status.setObjectName("gameCount")
        self.scan_status.setWordWrap(True)
        layout.addWidget(self.scan_status)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        self.import_button = QPushButton("Import Selected")
        self.import_button.setObjectName("addGameButton")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.accept_selected)
        footer.addWidget(close_button)
        footer.addWidget(self.import_button)
        layout.addLayout(footer)

        QTimer.singleShot(0, self.scan_all)

    def set_scanning(self, scanning: bool, message: str = "") -> None:
        for button in (self.scan_steam_button, self.scan_epic_button, self.scan_ea_button, self.scan_gog_button, self.scan_all_button):
            button.setEnabled(not scanning)
        if message:
            self.scan_status.setText(message)
        QApplication.processEvents()

    def scan_steam(self) -> None:
        self.set_scanning(True, "Scanning Steam libraries…")
        try:
            candidates, warnings = scan_installed_steam_games(self.steam_executable)
            self.populate(candidates, warnings)
        finally:
            self.set_scanning(False)

    def scan_epic(self) -> None:
        self.set_scanning(True, "Scanning Epic Games Launcher manifests…")
        try:
            candidates, warnings = scan_installed_epic_games()
            self.populate(candidates, warnings)
        finally:
            self.set_scanning(False)

    def scan_ea(self) -> None:
        self.set_scanning(True, "Scanning EA App and Origin games…")
        try:
            candidates, warnings = scan_ea_games()
            self.populate(candidates, warnings)
        finally:
            self.set_scanning(False)

    def scan_gog(self) -> None:
        self.set_scanning(True, "Scanning GOG games…")
        try:
            candidates, warnings = scan_gog_games()
            self.populate(candidates, warnings)
        finally:
            self.set_scanning(False)

    def scan_all(self) -> None:
        self.set_scanning(True, "Scanning Steam, Epic, EA/Origin and GOG libraries…")
        try:
            steam_games, steam_warnings = scan_installed_steam_games(self.steam_executable)
            epic_games, epic_warnings = scan_installed_epic_games()
            ea_games, ea_warnings = scan_ea_games()
            gog_games, gog_warnings = scan_gog_games()
            combined: dict[str, dict[str, Any]] = {}
            for candidate in steam_games + epic_games + ea_games + gog_games:
                combined.setdefault(game_identity(candidate), candidate)
            candidates = sorted(combined.values(), key=lambda item: (str(item.get("platform", "")), str(item.get("name", "")).casefold()))
            self.populate(candidates, steam_warnings + epic_warnings + ea_warnings + gog_warnings)
        finally:
            self.set_scanning(False)

    def populate(self, candidates: list[dict[str, Any]], warnings: list[str]) -> None:
        self.candidates = candidates
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        available_count = 0
        already_count = 0

        for candidate in candidates:
            row = self.table.rowCount()
            self.table.insertRow(row)
            already_added = any(games_are_duplicates(candidate, existing) for existing in self.existing_games)

            check_item = QTableWidgetItem()
            check_item.setData(Qt.ItemDataRole.UserRole, candidate)
            if already_added:
                check_item.setFlags(Qt.ItemFlag.ItemIsSelectable)
                check_item.setCheckState(Qt.CheckState.Unchecked)
                already_count += 1
            else:
                check_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                check_item.setCheckState(Qt.CheckState.Checked)
                available_count += 1

            location = str(candidate.get("install_location", "")) or "Detected from launcher manifest"
            status = "Already added" if already_added else "Ready to import"
            self.table.setItem(row, 0, check_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(candidate.get("name", "Unnamed game"))))
            self.table.setItem(row, 2, QTableWidgetItem(str(candidate.get("platform", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(location))
            self.table.setItem(row, 4, QTableWidgetItem(status))

        self.table.blockSignals(False)
        details = f"Found {len(candidates)} installed game(s): {available_count} available to import, {already_count} already in the library."
        if warnings:
            details += "\n" + " ".join(warnings)
        self.scan_status.setText(details)
        self.update_import_button()

    def selected_games(self) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                candidate = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(candidate, dict):
                    selected.append(migrate_game_record(dict(candidate)))
        return selected

    def update_import_button(self, _item: QTableWidgetItem | None = None) -> None:
        self.import_button.setEnabled(bool(self.selected_games()))

    def accept_selected(self) -> None:
        if not self.selected_games():
            QMessageBox.information(self, "No games selected", "Select at least one game to import.")
            return
        self.accept()


class LauncherWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1280, 780)
        self.setMinimumSize(900, 620)

        self.migrated_legacy_data = migrate_legacy_data()
        self.games: list[dict[str, Any]] = []
        self.settings = self.load_settings()
        self.current_filter = "library"
        self.grid_columns = 0
        self.launch_workers: list[SteamLaunchWorker] = []
        self.cover_worker: CoverDownloadWorker | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.update_progress_dialog: QProgressDialog | None = None
        self.running_game_ids: set[str] = set()
        self.launching_game_ids: set[str] = set()
        self.launch_deadlines: dict[str, float] = {}
        # Only a game explicitly launched from this app may become active.
        # This prevents unrelated processes from marking the first library item as RUNNING.
        self.active_game_id: str | None = None
        self.active_process_pid: int | None = None
        self.process_timer = QTimer(self)
        self.process_timer.setInterval(2500)
        self.process_timer.timeout.connect(self.refresh_running_games)

        self.create_ui()
        self.restore_window_preferences()
        self.load_games()
        self.apply_theme()
        self.refresh_all()
        self.process_timer.start()
        QTimer.singleShot(700, self.download_missing_covers)
        if getattr(sys, "frozen", False) and bool(self.settings.get("automatic_updates", True)):
            QTimer.singleShot(2500, lambda: self.check_for_updates(interactive=False))
        if self.migrated_legacy_data:
            self.statusBar().showMessage("Existing v2.0 library migrated to AppData", 7000)

    def restore_window_preferences(self) -> None:
        if bool(self.settings.get("remember_window", True)):
            geometry = str(self.settings.get("window_geometry", ""))
            if geometry:
                try:
                    raw = bytes.fromhex(geometry)
                    self.restoreGeometry(raw)
                except (ValueError, TypeError):
                    pass
        if bool(self.settings.get("start_maximized", False)):
            QTimer.singleShot(0, self.showMaximized)

    def load_settings(self) -> dict[str, Any]:
        settings = load_json(SETTINGS_FILE, {})
        if not isinstance(settings, dict):
            settings = {}
        if not settings.get("steam_executable"):
            settings["steam_executable"] = detect_steam_executable()
        settings.setdefault("theme", "dark")
        settings.setdefault("sort_order", "name_asc")
        settings.setdefault("automatic_updates", True)
        return settings

    def load_games(self) -> None:
        raw = load_json(DATA_FILE, [])
        self.games = [migrate_game_record(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def save_games(self) -> None:
        try:
            save_json(DATA_FILE, self.games)
        except OSError as error:
            QMessageBox.critical(self, "Save error", f"The game library could not be saved:\n{error}")

    def create_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 18)
        side.setSpacing(8)

        brand = QLabel("◉  LAUNCHER")
        brand.setObjectName("brand")
        side.addWidget(brand)
        section = QLabel("YOUR GAME LIBRARY")
        section.setObjectName("sidebarSection")
        side.addWidget(section)

        library = SidebarButton("▣   Library")
        favorites = SidebarButton("★   Favorites")
        recent = SidebarButton("◷   Recently Played")
        library.clicked.connect(lambda: self.set_filter("library"))
        favorites.clicked.connect(lambda: self.set_filter("favorites"))
        recent.clicked.connect(lambda: self.set_filter("recent"))
        library.setChecked(True)
        side.addWidget(library)
        side.addWidget(favorites)
        side.addWidget(recent)

        tools = QLabel("TOOLS")
        tools.setObjectName("sidebarSection")
        side.addSpacing(18)
        side.addWidget(tools)
        import_button = QPushButton("⇩   Import Games")
        import_button.setProperty("sidebarUtility", True)
        import_button.clicked.connect(self.open_import_games)
        side.addWidget(import_button)
        self.covers_button = QPushButton("▧   Download Covers")
        self.covers_button.setProperty("sidebarUtility", True)
        self.covers_button.clicked.connect(self.download_missing_covers)
        side.addWidget(self.covers_button)
        settings_button = QPushButton("⚙   Preferences")
        settings_button.setProperty("sidebarUtility", True)
        settings_button.clicked.connect(self.open_settings)
        side.addWidget(settings_button)
        about_button = QPushButton("ⓘ   About")
        about_button.setProperty("sidebarUtility", True)
        about_button.clicked.connect(self.open_about)
        side.addWidget(about_button)
        side.addStretch(1)
        root.addWidget(sidebar)

        main = QFrame()
        main.setObjectName("mainPanel")
        content = QVBoxLayout(main)
        content.setContentsMargins(30, 22, 30, 18)
        content.setSpacing(18)

        top = QHBoxLayout()
        brand_title = QLabel("V Game Launcher")
        brand_title.setObjectName("topNavigation")
        top.addWidget(brand_title)
        top.addStretch(1)
        self.library_stats = QLabel("Games: 0   •   Favorites: 0")
        self.library_stats.setObjectName("libraryStats")
        top.addWidget(self.library_stats)
        self.playing_status = QLabel("●  No game running")
        self.playing_status.setObjectName("playingStatusIdle")
        self.playing_status.setToolTip("Game activity status")
        top.addWidget(self.playing_status)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.refresh_grid)
        top.addWidget(self.search)
        self.add_button = QPushButton("＋  ADD GAME")
        self.add_button.setObjectName("addGameButton")
        self.add_button.clicked.connect(self.add_game)
        top.addWidget(self.add_button)
        content.addLayout(top)

        heading_row = QHBoxLayout()
        heading_box = QVBoxLayout()
        self.heading = QLabel("Library")
        self.heading.setObjectName("pageHeading")
        self.count_label = QLabel("0 games")
        self.count_label.setObjectName("gameCount")
        heading_box.addWidget(self.heading)
        heading_box.addWidget(self.count_label)
        heading_row.addLayout(heading_box)
        heading_row.addStretch(1)

        sort_label = QLabel("Sort by")
        sort_label.setObjectName("sortLabel")
        heading_row.addWidget(sort_label)
        self.sort_combo = QComboBox()
        self.sort_combo.setMinimumWidth(190)
        self.sort_combo.addItem("Name: A to Z", "name_asc")
        self.sort_combo.addItem("Name: Z to A", "name_desc")
        self.sort_combo.addItem("Recently played", "recent_desc")
        self.sort_combo.addItem("Least recently played", "recent_asc")
        self.sort_combo.addItem("Platform: A to Z", "platform")
        self.sort_combo.addItem("Favorites first", "favorites")
        saved_sort = str(self.settings.get("sort_order", "name_asc"))
        selected_index = self.sort_combo.findData(saved_sort)
        self.sort_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.sort_combo.currentIndexChanged.connect(self.sort_order_changed)
        heading_row.addWidget(self.sort_combo)
        content.addLayout(heading_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 12, 18)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        content.addWidget(self.scroll, 1)
        root.addWidget(main, 1)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self.setStatusBar(status)
        status.showMessage("Ready")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self.refresh_grid_if_needed)

    def calculate_columns(self) -> int:
        width = max(self.scroll.viewport().width() - 8, CARD_WIDTH)
        return max(1, width // (CARD_WIDTH + 18))

    def refresh_grid_if_needed(self) -> None:
        if self.calculate_columns() != self.grid_columns:
            self.refresh_grid()

    def filtered_games(self) -> list[dict[str, Any]]:
        if self.current_filter == "favorites":
            result = [game for game in self.games if game.get("favorite")]
        elif self.current_filter == "recent":
            result = [game for game in self.games if game.get("last_played")]
        else:
            result = list(self.games)

        query = self.search.text().strip().casefold()
        if query:
            result = [
                game for game in result
                if query in str(game.get("name", "")).casefold()
                or query in str(game.get("platform", "")).casefold()
            ]

        sort_order = str(self.sort_combo.currentData() or "name_asc")
        name_key = lambda game: str(game.get("name", "")).casefold()
        if sort_order == "name_desc":
            result.sort(key=name_key, reverse=True)
        elif sort_order == "recent_desc":
            result.sort(key=lambda game: (str(game.get("last_played", "")), name_key(game)), reverse=True)
        elif sort_order == "recent_asc":
            # Never-played games appear last; played games are oldest first.
            result.sort(key=lambda game: (not bool(game.get("last_played")), str(game.get("last_played", "")), name_key(game)))
        elif sort_order == "platform":
            result.sort(key=lambda game: (str(game.get("platform", "")).casefold(), name_key(game)))
        elif sort_order == "favorites":
            result.sort(key=lambda game: (not bool(game.get("favorite")), name_key(game)))
        else:
            result.sort(key=name_key)
        return result

    def sort_order_changed(self, _index: int = 0) -> None:
        self.settings["sort_order"] = str(self.sort_combo.currentData() or "name_asc")
        try:
            save_json(SETTINGS_FILE, self.settings)
        except OSError:
            pass
        self.refresh_grid()

    def clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh_grid(self) -> None:
        self.clear_grid()
        games = self.filtered_games()
        self.grid_columns = self.calculate_columns()
        if not games:
            empty = QLabel("No games found.\nUse ADD GAME to build your library.")
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(280)
            self.grid.addWidget(empty, 0, 0, 1, self.grid_columns)
        else:
            for index, game in enumerate(games):
                game_id = str(game.get("id", ""))
                has_active_game = bool(self.running_game_ids or self.launching_game_ids)
                is_running = game_id in self.running_game_ids
                is_launching = game_id in self.launching_game_ids
                is_blocked = has_active_game and not (is_running or is_launching)
                card = GameCard(game, is_running, is_launching, is_blocked)
                card.launch_requested.connect(self.launch_game)
                card.edit_requested.connect(self.edit_game)
                card.remove_requested.connect(self.remove_game)
                card.favorite_requested.connect(self.toggle_favorite)
                self.grid.addWidget(card, index // self.grid_columns, index % self.grid_columns)
        count = len(games)
        self.count_label.setText(f"{count} game" if count == 1 else f"{count} games")
        self.update_header_stats()
        self.update_playing_status()

    def active_game(self) -> dict[str, Any] | None:
        if not self.active_game_id:
            return None
        return next((game for game in self.games if str(game.get("id", "")) == self.active_game_id), None)

    def update_header_stats(self) -> None:
        total = len(self.games)
        favorites = sum(1 for game in self.games if game.get("favorite"))
        self.library_stats.setText(f"Games: {total}   •   Favorites: {favorites}")

    def update_playing_status(self) -> None:
        game = self.active_game()
        if game is None:
            self.playing_status.setText("●  No game running")
            self.playing_status.setObjectName("playingStatusIdle")
            self.playing_status.setToolTip("No game is currently running")
        else:
            game_id = str(game.get("id", ""))
            state = "Starting" if game_id in self.launching_game_ids else "Currently Playing"
            name = str(game.get("name", "Game"))
            self.playing_status.setText(f"●  {state}: {name}")
            self.playing_status.setObjectName("playingStatusActive")
            self.playing_status.setToolTip(f"{state}: {name}")
        self.playing_status.style().unpolish(self.playing_status)
        self.playing_status.style().polish(self.playing_status)

    def refresh_steam_status(self) -> None:
        steam_path = str(self.settings.get("steam_executable", ""))
        accounts = read_saved_steam_accounts(steam_path)
        if not steam_path:
            self.steam_status.setText("Steam not configured")
        elif not accounts:
            self.steam_status.setText("No saved accounts detected")
        else:
            recent = next((account for account in accounts if account.get("most_recent") == "1"), accounts[0])
            self.steam_status.setText(f"●  {recent['persona_name']}\n   {len(accounts)} saved account(s)")

    def refresh_all(self) -> None:
        self.refresh_grid()

    def set_filter(self, filter_name: str) -> None:
        self.current_filter = filter_name
        self.heading.setText({"library": "Library", "favorites": "Favorites", "recent": "Recently Played"}[filter_name])
        self.refresh_grid()

    def steam_accounts(self) -> list[dict[str, str]]:
        return read_saved_steam_accounts(str(self.settings.get("steam_executable", "")))

    def add_game(self) -> None:
        dialog = GameDialog(self.steam_accounts(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.games.append(dialog.result_game())
            self.save_games()
            self.refresh_all()
            self.statusBar().showMessage("Game added", 3000)

    def edit_game(self, game: dict[str, Any]) -> None:
        dialog = GameDialog(self.steam_accounts(), game=game, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        old_cover = str(game.get("cover", ""))
        updated = dialog.result_game()
        for index, existing in enumerate(self.games):
            if existing.get("id") == game.get("id"):
                self.games[index] = updated
                break
        self.save_games()
        if old_cover and old_cover != str(updated.get("cover", "")):
            delete_unused_cover(old_cover, self.games)
        self.refresh_all()

    def remove_game(self, game: dict[str, Any]) -> None:
        answer = QMessageBox.question(
            self,
            "Remove game",
            f"Remove “{game.get('name', 'this game')}” from the launcher?\n\nThe installed game will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed_cover = str(game.get("cover", ""))
        removed_id = str(game.get("id", ""))
        self.games = [item for item in self.games if item.get("id") != game.get("id")]
        if self.active_game_id == removed_id:
            self.active_game_id = None
            self.active_process_pid = None
            self.running_game_ids.clear()
            self.launching_game_ids.clear()
            self.launch_deadlines.clear()
        self.save_games()
        delete_unused_cover(removed_cover, self.games)
        self.refresh_all()

    def toggle_favorite(self, game: dict[str, Any]) -> None:
        for existing in self.games:
            if existing.get("id") == game.get("id"):
                existing["favorite"] = not bool(existing.get("favorite"))
                break
        self.save_games()
        self.refresh_grid()

    def mark_as_played(self, game: dict[str, Any]) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        for existing in self.games:
            if existing.get("id") == game.get("id"):
                existing["last_played"] = timestamp
                break
        self.save_games()

    def launch_game(self, game: dict[str, Any]) -> None:
        game_id = str(game.get("id", ""))
        active_ids = self.running_game_ids | self.launching_game_ids
        if active_ids and game_id not in active_ids:
            active = self.active_game()
            active_name = str(active.get("name", "another game")) if active else "another game"
            self.statusBar().showMessage(f"Close {active_name} before launching another game.", 5000)
            return
        if game_id in active_ids:
            return
        self.set_game_launching(game)
        if str(game.get("platform")) == "Steam":
            self.launch_steam_game(game)
            return
        target = str(game.get("target", "")).strip()
        if not target:
            QMessageBox.critical(self, "Launch error", "No executable or launch URI is configured.")
            return
        try:
            if target.lower().startswith(("steam://", "ea://", "link2ea://", "com.epicgames.launcher://", "uplay://", "http://", "https://")):
                os.startfile(target)
                self.active_process_pid = None
            else:
                target = normalize_path(target)
                if not Path(target).is_file():
                    raise FileNotFoundError(f"The game executable was not found:\n{target}")
                process = subprocess.Popen([target], cwd=str(Path(target).parent), shell=False)
                self.active_process_pid = process.pid
            self.mark_as_played(game)
            self.statusBar().showMessage(f"Launching {game.get('name', 'game')}…", 5000)
        except OSError as error:
            self.clear_game_launching(game)
            QMessageBox.critical(self, "Launch error", f"The game could not be started:\n{error}")

    def launch_steam_game(self, game: dict[str, Any]) -> None:
        steam_executable = str(self.settings.get("steam_executable", ""))
        if not steam_executable or not Path(steam_executable).is_file():
            answer = QMessageBox.question(self, "Steam not configured", "Steam.exe has not been configured. Open Settings now?")
            if answer == QMessageBox.StandardButton.Yes:
                self.open_settings()
            self.clear_game_launching(game)
            return

        app_id = str(game.get("steam_app_id", "")).strip()
        if not app_id.isdigit():
            self.clear_game_launching(game)
            QMessageBox.critical(self, "Steam launch error", "This game does not have a valid Steam App ID.")
            return

        account_name = str(game.get("steam_account", "")).strip()
        mode = str(game.get("steam_mode", "current"))
        restart_steam = bool(account_name) or mode == "offline"

        if restart_steam and steam_is_running():
            account_text = f" using account “{account_name}”" if account_name else ""
            mode_text = " in Offline Mode" if mode == "offline" else ""
            answer = QMessageBox.question(
                self,
                "Restart Steam",
                f"Steam must be restarted{account_text}{mode_text}.\n\nClose Steam and continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.clear_game_launching(game)
                return

        self.add_button.setEnabled(False)
        worker = SteamLaunchWorker(steam_executable, app_id, account_name, mode, restart_steam)
        self.launch_workers.append(worker)
        worker.status_changed.connect(self.statusBar().showMessage)
        worker.launch_succeeded.connect(lambda selected=game: self.steam_launch_succeeded(selected))
        worker.launch_failed.connect(lambda error, selected=game: self.steam_launch_failed(selected, error))
        worker.finished.connect(lambda: self.cleanup_worker(worker))
        worker.start()

    def steam_launch_succeeded(self, game: dict[str, Any]) -> None:
        self.mark_as_played(game)
        self.add_button.setEnabled(True)
        self.statusBar().showMessage(f"Launching {game.get('name', 'Steam game')}…", 5000)
        if self.current_filter == "recent":
            self.refresh_grid()

    def steam_launch_failed(self, game: dict[str, Any], error: str) -> None:
        self.clear_game_launching(game)
        self.add_button.setEnabled(True)
        QMessageBox.critical(self, "Steam launch error", f"The Steam game could not be started:\n{error}")

    def cleanup_worker(self, worker: SteamLaunchWorker) -> None:
        if worker in self.launch_workers:
            self.launch_workers.remove(worker)
        worker.deleteLater()
        self.add_button.setEnabled(True)

    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme_stylesheet(str(self.settings.get("theme", "dark"))))

    def set_game_launching(self, game: dict[str, Any]) -> None:
        game_id = str(game.get("id", ""))
        if not game_id:
            return
        self.active_game_id = game_id
        self.active_process_pid = None
        self.launching_game_ids = {game_id}
        self.running_game_ids.clear()
        self.launch_deadlines = {game_id: time.monotonic() + 45.0}
        self.refresh_grid()

    def clear_game_launching(self, game: dict[str, Any]) -> None:
        game_id = str(game.get("id", ""))
        self.launching_game_ids.discard(game_id)
        self.launch_deadlines.pop(game_id, None)
        if self.active_game_id == game_id and game_id not in self.running_game_ids:
            self.active_game_id = None
            self.active_process_pid = None
        self.refresh_grid()

    @staticmethod
    def process_id_exists(pid: int | None) -> bool:
        if not pid or sys.platform != "win32":
            return False
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return bool(re.search(rf'"[^"]+","{pid}"', completed.stdout))
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def running_process_names() -> set[str]:
        if sys.platform != "win32":
            return set()
        try:
            completed = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            names: set[str] = set()
            for line in completed.stdout.splitlines():
                match = re.match(r'^"([^"]+)"', line.strip())
                if match:
                    names.add(match.group(1).casefold())
            return names
        except (OSError, subprocess.SubprocessError):
            return set()

    @staticmethod
    def game_executable_names(game: dict[str, Any]) -> set[str]:
        candidates: set[str] = set()
        for key in ("epic_launch_executable", "target"):
            value = str(game.get(key, "")).strip()
            if value and "://" not in value and value.lower().endswith(".exe"):
                candidates.add(Path(normalize_path(value)).name.casefold())

        install_location = str(game.get("install_location", "")).strip()
        if install_location:
            folder = Path(normalize_path(install_location))
            if folder.is_dir():
                game_name_words = [word for word in re.findall(r"[a-z0-9]+", str(game.get("name", "")).casefold()) if len(word) > 2]
                scored: list[tuple[int, str]] = []
                try:
                    for exe in folder.rglob("*.exe"):
                        relative_depth = len(exe.relative_to(folder).parts)
                        if relative_depth > 4:
                            continue
                        lower = exe.name.casefold()
                        if any(skip in lower for skip in ("unins", "uninstall", "crashreport", "reporter", "launcher", "setup", "redist", "helper")):
                            continue
                        score = sum(3 for word in game_name_words if word in lower) - relative_depth
                        scored.append((score, lower))
                except OSError:
                    pass
                scored.sort(reverse=True)
                for _, name in scored[:4]:
                    candidates.add(name)
        return candidates

    def clear_active_game(self) -> None:
        self.active_game_id = None
        self.active_process_pid = None
        self.running_game_ids.clear()
        self.launching_game_ids.clear()
        self.launch_deadlines.clear()
        self.refresh_grid()

    def refresh_running_games(self) -> None:
        game = self.active_game()
        if game is None:
            if self.running_game_ids or self.launching_game_ids:
                self.clear_active_game()
            else:
                self.update_playing_status()
            return

        game_id = str(game.get("id", ""))
        now = time.monotonic()
        is_running = False

        # For a directly launched executable, the exact PID is the primary signal.
        if self.active_process_pid:
            is_running = self.process_id_exists(self.active_process_pid)

        # Steam/Epic/EA URI launches do not return the game's PID. In that case,
        # inspect executable names only for the game the user explicitly launched.
        if not is_running:
            executable_names = self.game_executable_names(game)
            if executable_names:
                is_running = bool(executable_names & self.running_process_names())

        if is_running:
            changed = game_id not in self.running_game_ids or bool(self.launching_game_ids)
            self.running_game_ids = {game_id}
            self.launching_game_ids.clear()
            self.launch_deadlines.clear()
            if changed:
                self.refresh_grid()
            else:
                self.update_playing_status()
            return

        if game_id in self.running_game_ids:
            self.clear_active_game()
            return

        deadline = self.launch_deadlines.get(game_id, 0)
        if game_id in self.launching_game_ids and now >= deadline:
            self.clear_active_game()
        else:
            self.update_playing_status()

    def games_missing_covers(self) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for game in self.games:
            cover = str(game.get("cover", "")).strip()
            platform = str(game.get("platform", "")).strip().casefold()
            if platform not in {"steam", "epic games"}:
                continue
            if not cover or not Path(cover).is_file():
                missing.append(game)
        return missing

    def download_missing_covers(self) -> None:
        if self.cover_worker is not None and self.cover_worker.isRunning():
            self.statusBar().showMessage("Cover download is already running", 3000)
            return
        missing = self.games_missing_covers()
        if not missing:
            self.statusBar().showMessage("All Steam and Epic games already have covers", 4000)
            return

        self.covers_button.setEnabled(False)
        worker = CoverDownloadWorker(missing, str(self.settings.get("steam_executable", "")))
        self.cover_worker = worker
        worker.progress_changed.connect(self.statusBar().showMessage)
        worker.cover_downloaded.connect(self.apply_downloaded_cover)
        worker.completed.connect(self.cover_download_completed)
        worker.finished.connect(lambda: self.cleanup_cover_worker(worker))
        worker.start()

    def apply_downloaded_cover(self, game_id: str, cover_path: str) -> None:
        for game in self.games:
            if str(game.get("id", "")) == game_id:
                game["cover"] = cover_path
                break

    def cover_download_completed(self, downloaded_count: int, total: int) -> None:
        if downloaded_count:
            self.save_games()
            self.refresh_grid()
        failed_count = max(0, total - downloaded_count)
        if failed_count:
            self.statusBar().showMessage(
                f"Downloaded {downloaded_count} cover(s); {failed_count} could not be found",
                8000,
            )
        else:
            self.statusBar().showMessage(f"Downloaded {downloaded_count} cover(s)", 6000)

    def cleanup_cover_worker(self, worker: CoverDownloadWorker) -> None:
        if self.cover_worker is worker:
            self.cover_worker = None
        worker.deleteLater()
        self.covers_button.setEnabled(True)

    def open_import_games(self) -> None:
        dialog = ImportGamesDialog(str(self.settings.get("steam_executable", "")), self.games, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_games()
        imported_count = 0
        for candidate in selected:
            if any(games_are_duplicates(candidate, existing) for existing in self.games):
                continue
            self.games.append(candidate)
            imported_count += 1
        if imported_count:
            self.save_games()
            self.refresh_all()
            self.statusBar().showMessage(f"Imported {imported_count} game(s)", 5000)
            QTimer.singleShot(100, self.download_missing_covers)
        else:
            QMessageBox.information(self, "Nothing imported", "The selected games are already present in the library.")

    def check_for_updates(self, interactive: bool = True) -> None:
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            if interactive:
                QMessageBox.information(self, "Update check", "An update check is already in progress.")
            return

        self.statusBar().showMessage("Checking GitHub for updates…")
        worker = UpdateCheckWorker(self)
        self.update_check_worker = worker
        worker.result_ready.connect(lambda result, manual=interactive: self.handle_update_check_result(result, manual))
        worker.finished.connect(lambda: self.cleanup_update_check_worker(worker))
        worker.start()

    def cleanup_update_check_worker(self, worker: UpdateCheckWorker) -> None:
        if self.update_check_worker is worker:
            self.update_check_worker = None
        worker.deleteLater()

    def handle_update_check_result(self, result: dict[str, Any], interactive: bool) -> None:
        status = str(result.get("status", "error"))
        if status == "error":
            message = str(result.get("message", "The update check failed."))
            self.statusBar().showMessage(message, 8000)
            if interactive:
                QMessageBox.warning(self, "Update check failed", message)
            return

        latest_version = str(result.get("latest_version", "")).strip()
        if status == "up_to_date":
            self.statusBar().showMessage(f"V Game Launcher {APP_VERSION} is up to date.", 6000)
            if interactive:
                QMessageBox.information(
                    self,
                    "No updates available",
                    f"You are using the latest version of V Game Launcher ({APP_VERSION}).",
                )
            return

        self.statusBar().showMessage(f"V Game Launcher {latest_version} is available.", 10000)
        self.prompt_for_update(result)

    def prompt_for_update(self, information: dict[str, Any]) -> None:
        latest_version = str(information.get("latest_version", "")).strip()
        asset = information.get("asset")
        release_url = str(information.get("release_url", GITHUB_RELEASES_URL)).strip() or GITHUB_RELEASES_URL
        notes = str(information.get("release_notes", "")).strip()

        message = QMessageBox(self)
        message.setWindowTitle("Update available")
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(f"V Game Launcher {latest_version} is available.")
        if isinstance(asset, dict) and getattr(sys, "frozen", False):
            message.setInformativeText(
                f"Installed version: {APP_VERSION}\n\n"
                "Download and install the update now? The launcher will restart automatically."
            )
            install_button = message.addButton("Download and Install", QMessageBox.ButtonRole.AcceptRole)
            later_button = message.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            message.setDefaultButton(install_button)
            if notes:
                message.setDetailedText(notes[:12000])
            message.exec()
            if message.clickedButton() == install_button:
                self.start_update_download(information)
            elif message.clickedButton() == later_button:
                self.statusBar().showMessage("Update postponed.", 4000)
            return

        if not isinstance(asset, dict):
            message.setInformativeText(
                "The release exists, but it does not contain a compatible portable .exe asset. "
                "Open the release page to download it manually."
            )
        else:
            message.setInformativeText(
                "Automatic installation is available in the packaged Windows .exe version. "
                "Open the release page to download it manually."
            )
        open_button = message.addButton("Open Release Page", QMessageBox.ButtonRole.AcceptRole)
        message.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        if notes:
            message.setDetailedText(notes[:12000])
        message.exec()
        if message.clickedButton() == open_button:
            try:
                os.startfile(release_url)
            except OSError:
                pass

    def start_update_download(self, information: dict[str, Any]) -> None:
        asset = information.get("asset")
        if not isinstance(asset, dict):
            QMessageBox.warning(self, "Update unavailable", "No compatible Windows .exe asset was found in the release.")
            return
        if self.update_download_worker is not None and self.update_download_worker.isRunning():
            QMessageBox.information(self, "Update download", "An update is already being downloaded.")
            return

        target_executable = Path(sys.executable).resolve()
        try:
            target_executable.parent.mkdir(parents=True, exist_ok=True)
            permission_test = target_executable.parent / f".vgame_update_test_{uuid.uuid4().hex}"
            permission_test.write_text("test", encoding="utf-8")
            permission_test.unlink(missing_ok=True)
        except OSError as error:
            QMessageBox.warning(
                self,
                "Update permission required",
                f"The launcher cannot update files in this folder:\n{target_executable.parent}\n\n{error}",
            )
            return

        latest_version = str(information.get("latest_version", "latest"))
        progress = QProgressDialog("Preparing update download…", "Cancel", 0, 100, self)
        progress.setWindowTitle(f"Downloading {latest_version}")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self.update_progress_dialog = progress

        worker = UpdateDownloadWorker(asset, latest_version)
        self.update_download_worker = worker
        worker.progress_changed.connect(self.update_download_progress)
        worker.completed.connect(self.update_download_completed)
        worker.failed.connect(self.update_download_failed)
        worker.cancelled.connect(self.update_download_cancelled)
        worker.finished.connect(lambda: self.cleanup_update_download_worker(worker))
        progress.canceled.connect(worker.requestInterruption)
        worker.start()
        progress.show()

    def update_download_progress(self, downloaded: int, total: int) -> None:
        if self.update_progress_dialog is None:
            return
        if total > 0:
            percent = max(0, min(100, int(downloaded * 100 / total)))
            self.update_progress_dialog.setRange(0, 100)
            self.update_progress_dialog.setValue(percent)
            self.update_progress_dialog.setLabelText(
                f"Downloading update… {downloaded / (1024 * 1024):.1f} MB / {total / (1024 * 1024):.1f} MB"
            )
        else:
            self.update_progress_dialog.setRange(0, 0)
            self.update_progress_dialog.setLabelText(f"Downloading update… {downloaded / (1024 * 1024):.1f} MB")

    def update_download_completed(self, downloaded_path: str) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.setValue(100)
            self.update_progress_dialog.close()
            self.update_progress_dialog.deleteLater()
            self.update_progress_dialog = None

        downloaded = Path(downloaded_path)
        target = Path(sys.executable).resolve()
        try:
            script = create_windows_update_script(downloaded, target)
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(
                ["cmd.exe", "/d", "/c", str(script)],
                cwd=str(script.parent),
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as error:
            QMessageBox.critical(self, "Update installation failed", f"The updater could not be started:\n{error}")
            return

        self.statusBar().showMessage("Update downloaded. Restarting V Game Launcher…")
        QApplication.quit()

    def update_download_failed(self, message: str) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog.deleteLater()
            self.update_progress_dialog = None
        QMessageBox.warning(self, "Update download failed", message or "The update could not be downloaded.")

    def update_download_cancelled(self) -> None:
        if self.update_progress_dialog is not None:
            self.update_progress_dialog.close()
            self.update_progress_dialog.deleteLater()
            self.update_progress_dialog = None
        self.statusBar().showMessage("Update download cancelled.", 5000)

    def cleanup_update_download_worker(self, worker: UpdateDownloadWorker) -> None:
        if self.update_download_worker is worker:
            self.update_download_worker = None
        worker.deleteLater()

    def open_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("About V Game Launcher")
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        title = QLabel("V Game Launcher")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("gameCount")
        layout.addWidget(version)
        details = QLabel(
            "Created by Vladimir Rankovic\n\n"
            "A unified Windows game library for Steam, Epic Games, EA App / Origin, GOG Galaxy and local games.\n\n"
            "Built with Python and PySide6.\nLicense: MIT License"
        )
        details.setWordWrap(True)
        details.setObjectName("settingsPanel")
        layout.addWidget(details)
        buttons_row = QHBoxLayout()
        github = QPushButton("Open GitHub")
        github.clicked.connect(lambda: os.startfile(GITHUB_REPOSITORY_URL))
        updates = QPushButton("Check for Updates")
        updates.clicked.connect(lambda: self.check_for_updates(interactive=True))
        buttons_row.addWidget(github)
        buttons_row.addWidget(updates)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_saved.connect(self.apply_settings)
        dialog.exec()

    def apply_settings(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        try:
            save_json(SETTINGS_FILE, self.settings)
        except OSError as error:
            QMessageBox.critical(self, "Settings error", f"Settings could not be saved:\n{error}")
        self.apply_theme()
        self.refresh_all()

    def closeEvent(self, event) -> None:
        if bool(self.settings.get("remember_window", True)):
            self.settings["window_geometry"] = bytes(self.saveGeometry()).hex()
            try:
                save_json(SETTINGS_FILE, self.settings)
            except OSError:
                pass
        for worker in self.launch_workers:
            worker.requestInterruption()
            worker.wait(1500)
        if self.cover_worker is not None and self.cover_worker.isRunning():
            self.cover_worker.requestInterruption()
            self.cover_worker.wait(2500)
        if self.update_check_worker is not None and self.update_check_worker.isRunning():
            self.update_check_worker.requestInterruption()
            self.update_check_worker.wait((UPDATE_CHECK_TIMEOUT + 2) * 1000)
        if self.update_download_worker is not None and self.update_download_worker.isRunning():
            self.update_download_worker.requestInterruption()
            self.update_download_worker.wait(3000)
        event.accept()


DARK_STYLE_SHEET = f"""
* {{ font-family: 'Segoe UI'; font-size: 10pt; color: {TEXT_PRIMARY}; }}
QMainWindow, QWidget {{ background: {BG_MAIN}; }}
QFrame#sidebar {{ background: {BG_SIDEBAR}; border-right: 1px solid {BORDER}; }}
QFrame#mainPanel {{ background: {BG_MAIN}; }}
QLabel#brand {{ font-size: 18pt; font-weight: 700; padding: 4px 2px 20px 2px; }}
QLabel#sidebarSection {{ color: {TEXT_SECONDARY}; font-size: 8pt; font-weight: 700; padding: 10px 8px 4px 8px; }}
QPushButton[sidebarButton='true'], QPushButton[sidebarUtility='true'] {{ text-align: left; background: transparent; color: {TEXT_SECONDARY}; border: none; border-radius: 6px; padding: 10px 12px; font-weight: 600; }}
QPushButton[sidebarButton='true']:hover, QPushButton[sidebarUtility='true']:hover {{ background: {BG_PANEL}; color: {TEXT_PRIMARY}; }}
QPushButton[sidebarButton='true']:checked {{ background: #193a54; color: {ACCENT_BLUE_HOVER}; border-left: 3px solid {ACCENT_BLUE}; }}
QLabel#steamAccountStatus {{ background: {BG_DEEPEST}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; border-radius: 7px; padding: 10px; }}
QLabel#topNavigation {{ color: {TEXT_SECONDARY}; font-weight: 600; letter-spacing: 1px; }}
QLabel#pageHeading {{ font-size: 22pt; font-weight: 700; }}
QLabel#gameCount {{ color: {TEXT_SECONDARY}; }}
QLineEdit, QComboBox {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 8px 10px; min-height: 20px; selection-background-color: {ACCENT_BLUE}; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT_BLUE}; }}
QComboBox QAbstractItemView {{ background: {BG_PANEL}; border: 1px solid {BORDER}; selection-background-color: #24557a; }}
QPushButton {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 8px 13px; font-weight: 600; }}
QPushButton:hover {{ background: {BG_PANEL_HOVER}; border-color: #3d5d79; }}
QPushButton#addGameButton {{ background: {ACCENT_BLUE}; color: white; border: none; padding: 9px 16px; }}
QPushButton#addGameButton:hover {{ background: {ACCENT_BLUE_HOVER}; }}
QFrame#gameCard {{ background: {BG_PANEL}; border: 1px solid #24384b; border-radius: 9px; }}
QFrame#gameCard:hover {{ background: {BG_PANEL_HOVER}; border: 1px solid #3f6686; }}
QFrame#runningGameCard {{ background: {BG_PANEL}; border: 2px solid #d9822b; border-radius: 9px; }}
QFrame#coverContainer {{ background: {BG_DEEPEST}; border: none; border-radius: 8px; }}
QLabel#gameTitle {{ font-weight: 700; font-size: 11pt; }}
QLabel#platformLabel {{ color: {TEXT_SECONDARY}; font-size: 9pt; }}
QPushButton#playButton {{ background: {ACCENT_GREEN}; color: white; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }}
QPushButton#playButton:hover {{ background: {ACCENT_GREEN_HOVER}; }}
QPushButton#runningButton {{ background: #d9822b; color: white; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }}
QPushButton#startingButton {{ background: #5b6f82; color: white; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }}
QPushButton#blockedPlayButton {{ background: #3b4650; color: #89939c; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }}
QLabel#runningBadge {{ background: rgba(15, 20, 26, 220); color: #f4a340; border: 1px solid #d9822b; border-radius: 5px; padding: 4px 7px; font-size: 8pt; font-weight: 700; }}
QLabel#playingStatusIdle {{ color: {TEXT_SECONDARY}; padding: 7px 10px; }}
QLabel#playingStatusActive {{ background: #3c2a18; color: #f4a340; border: 1px solid #d9822b; border-radius: 6px; padding: 7px 10px; font-weight: 700; }}
QToolButton#favoriteButton {{ background: rgba(10, 15, 22, 210); color: #f4c95d; border: 1px solid rgba(255, 255, 255, 35); border-radius: 16px; font-size: 15pt; }}
QToolButton#favoriteButton:hover {{ background: rgba(27, 40, 56, 235); }}
QScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ background: {BG_MAIN}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3b5268; min-height: 30px; border-radius: 6px; }}
QScrollBar::handle:vertical:hover {{ background: #56748f; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLabel#emptyState {{ color: {TEXT_SECONDARY}; font-size: 13pt; border: 1px dashed {BORDER}; border-radius: 10px; }}
QLabel#dialogNote {{ color: {TEXT_SECONDARY}; font-size: 9pt; padding: 7px 0; }}
QLabel#sectionTitle {{ font-size: 16pt; font-weight: 700; padding-bottom: 8px; }}
QLabel#settingsPanel {{ background: {BG_DEEPEST}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; color: {TEXT_SECONDARY}; }}
QTableWidget {{ background: {BG_DEEPEST}; alternate-background-color: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 7px; gridline-color: {BORDER}; selection-background-color: #24557a; }}
QTableWidget::item {{ padding: 7px; }}
QHeaderView::section {{ background: {BG_PANEL}; color: {TEXT_PRIMARY}; border: none; border-right: 1px solid {BORDER}; border-bottom: 1px solid {BORDER}; padding: 8px; font-weight: 700; }}
QMenu {{ background: {BG_PANEL}; border: 1px solid {BORDER}; padding: 5px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: #24557a; }}
QStatusBar {{ background: {BG_DEEPEST}; color: {TEXT_SECONDARY}; border-top: 1px solid {BORDER}; }}
"""


LIGHT_STYLE_SHEET = """
* { font-family: 'Segoe UI'; font-size: 10pt; color: #1e2933; }
QMainWindow, QWidget { background: #eef2f6; }
QFrame#sidebar { background: #ffffff; border-right: 1px solid #c8d1da; }
QFrame#mainPanel { background: #eef2f6; }
QLabel#brand { font-size: 18pt; font-weight: 700; padding: 4px 2px 20px 2px; color: #17212b; }
QLabel#sidebarSection { color: #687684; font-size: 8pt; font-weight: 700; padding: 10px 8px 4px 8px; }
QPushButton[sidebarButton='true'], QPushButton[sidebarUtility='true'] { text-align: left; background: transparent; color: #5d6b78; border: none; border-radius: 6px; padding: 10px 12px; font-weight: 600; }
QPushButton[sidebarButton='true']:hover, QPushButton[sidebarUtility='true']:hover { background: #e7edf3; color: #17212b; }
QPushButton[sidebarButton='true']:checked { background: #d7ecfb; color: #0876b9; border-left: 3px solid #149be0; }
QLabel#topNavigation { color: #687684; font-weight: 600; letter-spacing: 1px; }
QLabel#pageHeading { font-size: 22pt; font-weight: 700; color: #17212b; }
QLabel#gameCount { color: #687684; }
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #b8c4cf; border-radius: 6px; padding: 8px 10px; min-height: 20px; selection-background-color: #149be0; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #149be0; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #b8c4cf; selection-background-color: #d7ecfb; }
QPushButton { background: #ffffff; border: 1px solid #b8c4cf; border-radius: 6px; padding: 8px 13px; font-weight: 600; }
QPushButton:hover { background: #e7edf3; border-color: #8fa2b3; }
QPushButton#addGameButton { background: #149be0; color: white; border: none; padding: 9px 16px; }
QPushButton#addGameButton:hover { background: #28aaf0; }
QFrame#gameCard { background: #ffffff; border: 1px solid #cad3dc; border-radius: 9px; }
QFrame#gameCard:hover { background: #f8fafc; border: 1px solid #8fb4cf; }
QFrame#coverContainer { background: #dfe6ec; border: none; border-radius: 8px; }
QLabel#gameTitle { font-weight: 700; font-size: 11pt; color: #17212b; }
QLabel#platformLabel { color: #687684; font-size: 9pt; }
QPushButton#playButton { background: #66a71f; color: white; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }
QPushButton#playButton:hover { background: #78bb2d; }
QPushButton#runningButton { background: #d9822b; color: white; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }
QPushButton#startingButton { background: #738392; color: white; border: none; border-radius: 5px; padding: 7px; font-weight: 700; letter-spacing: 1px; }
QToolButton#favoriteButton { background: rgba(255,255,255,220); color: #bd8700; border: 1px solid rgba(0,0,0,35); border-radius: 16px; font-size: 15pt; }
QScrollArea { background: transparent; }
QScrollBar:vertical { background: #eef2f6; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #a9b6c1; min-height: 30px; border-radius: 6px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLabel#emptyState { color: #687684; font-size: 13pt; border: 1px dashed #b8c4cf; border-radius: 10px; }
QLabel#dialogNote { color: #687684; font-size: 9pt; padding: 7px 0; }
QLabel#sectionTitle { font-size: 16pt; font-weight: 700; padding-bottom: 8px; color: #17212b; }
QLabel#settingsPanel { background: #ffffff; border: 1px solid #c8d1da; border-radius: 8px; padding: 14px; color: #5d6b78; }
QTableWidget { background: #ffffff; alternate-background-color: #f5f7f9; border: 1px solid #c8d1da; border-radius: 7px; gridline-color: #d5dde4; selection-background-color: #d7ecfb; }
QTableWidget::item { padding: 7px; }
QHeaderView::section { background: #e7edf3; color: #17212b; border: none; border-right: 1px solid #c8d1da; border-bottom: 1px solid #c8d1da; padding: 8px; font-weight: 700; }
QMenu { background: #ffffff; border: 1px solid #c8d1da; padding: 5px; }
QMenu::item { padding: 8px 24px; border-radius: 4px; }
QMenu::item:selected { background: #d7ecfb; }
QStatusBar { background: #ffffff; color: #687684; border-top: 1px solid #c8d1da; }
"""


def theme_stylesheet(theme: str) -> str:
    return LIGHT_STYLE_SHEET if theme.casefold() == "light" else DARK_STYLE_SHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(":/vgame_icon.png"))
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLE_SHEET)
    window = LauncherWindow()
    window.setWindowIcon(QIcon(":/vgame_icon.png"))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
