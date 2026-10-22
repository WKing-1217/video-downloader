"""Verify real Windows ownership and stacking using only this process's windows."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
work = root / "build/native-player-review"
work.mkdir(exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, str(root))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from desktop_verify import prepare_fonts
from media_player import GalleryDialog, PlayerDialog
from ui_theme import stylesheet

user = ctypes.WinDLL("user32", use_last_error=True)
user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user.GetWindow.restype = wintypes.HWND
user.GetTopWindow.argtypes = [wintypes.HWND]
user.GetTopWindow.restype = wintypes.HWND
user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user.GetWindowLongPtrW.restype = ctypes.c_ssize_t

def owner(widget):
    return int(user.GetWindow(int(widget.winId()), 4) or 0)

def above(first, second):
    cursor = user.GetTopWindow(None)
    while cursor:
        if int(cursor) == int(first.winId()):
            return True
        if int(cursor) == int(second.winId()):
            return False
        cursor = user.GetWindow(cursor, 2)
    return False

app = QApplication([])
app.setStyleSheet(stylesheet())
prepare_fonts()
main = QWidget()
main.setWindowTitle("视频下载器 · 窗口关系检查")
main.resize(900, 650)
main.show()
checks = {}
windows = []

def check(name, value):
    assert value, name
    checks[name] = True

try:
    baseline = QDialog(main)
    baseline.show()
    check("old_dialog_has_native_owner", owner(baseline) == int(main.winId()))
    baseline.close()
    player = PlayerDialog(root / "build/v2-fixtures/sample.mp4", "独立播放窗口检查", main)
    windows.append(player)
    player.show()
    deadline = time.monotonic() + 10
    while player.video.image is None and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(30)
    check("player_decodes_real_video", player.video.image is not None)
    check("player_has_no_win32_owner", owner(player) == 0)
    check("player_has_no_qt_transient_owner", player.windowHandle().transientParent() is None)
    check("player_is_not_topmost", not user.GetWindowLongPtrW(int(player.winId()), -20) & 8)
    style = user.GetWindowLongPtrW(int(player.winId()), -16)
    check("native_minimize_and_maximize_buttons", bool(style & 0x20000) and bool(style & 0x10000))
    player.raise_()
    QTest.qWait(120)
    check("player_can_move_above_library", above(player, main))
    main.raise_()
    main.activateWindow()
    QTest.qWait(120)
    check("library_can_move_above_player", above(main, player))
    player.showMinimized()
    QTest.qWait(100)
    check("player_minimizes_independently", player.isMinimized() and not main.isMinimized())
    player.showMaximized()
    QTest.qWait(100)
    check("player_maximizes", player.isMaximized())
    player.showNormal()
    player.raise_()
    player.player.pause()
    QTest.qWait(80)
    player.grab().save(str(work / "independent-player.png"))
    gallery = GalleryDialog({"title": "图片窗口检查", "path": str(work), "metadata": '{"assets":[]}'}, main)
    windows.append(gallery)
    gallery.show()
    QTest.qWait(80)
    check("gallery_also_has_no_native_owner", owner(gallery) == 0)
    main.raise_()
    QTest.qWait(80)
    check("library_can_move_above_gallery", above(main, gallery))
finally:
    for window in windows:
        window.close()
    main.close()
    QTest.qWait(80)
    result = {"passed": len(checks) == 12, "checks": checks, "native_windows": True}
    (work / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
assert result["passed"]
