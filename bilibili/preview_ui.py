"""A local design review using separate settings and copies of sample media.

Interactive: python preview_ui.py
QA:          python preview_ui.py --capture --scale 1.5
Only --capture supplies illustrative task states. Interactive downloads are real.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent


def seed_samples(store, output):
    selections = (("*手写*.mp4", "手写的从前 · 周杰伦"),
                  ("*别怕*.mp4", "别怕变老 · 王以太、艾热 AIR"),
                  ("*朋友*.mp4", "朋友的酒 · 现场音乐影像"))
    output.mkdir(parents=True, exist_ok=True)
    from runtime_paths import tool
    recorded = store.rows(include_hidden=True)
    for number, (pattern, title) in enumerate(selections, 1):
        # Deleted or migrated preview media must not be silently seeded again.
        if any(row["title"] == title for row in recorded):
            continue
        sources = sorted((ROOT.parent / "video").glob(pattern))
        if not sources:
            continue
        source = sources[0]
        target = output / f"示例作品 {number:02d}.mp4"
        if not target.exists():
            shutil.copy2(source, target)  # A copy: preview deletion cannot touch the original.
        receipt = source.with_suffix(source.suffix + ".info.json")
        try:
            duration = float(json.loads(receipt.read_text(encoding="utf-8")).get("duration") or 0)
        except (OSError, ValueError, AttributeError):
            duration = 0
        if not duration:
            probe = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=noprint_wrappers=1:nokey=1", str(target)],
                                   capture_output=True, text=True, timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                duration = float(probe.stdout.strip())
            except ValueError:
                continue
        metadata = {"title": title, "duration": duration, "size": target.stat().st_size, "platform": "bilibili"}
        store.upsert(target, metadata, completed=not any(row["path"] == str(target) for row in store.rows()))


def capture_review(app, window, directory):
    from PySide6.QtCore import Qt, QPoint, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel, QFrame
    from media_player import GalleryDialog
    from ui_theme import COLORS, DIALOG, METRICS, RAIL
    from ui_widgets import RecentDelegate

    directory.mkdir(parents=True, exist_ok=True)
    checks = {}
    screenshots = []

    def wait(condition, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(25)
            if condition():
                return
        raise AssertionError("UI review timed out")

    def shot(name, widget=window):
        QTest.qWait(120)
        assert widget.grab().save(str(directory / (name + ".png")))
        screenshots.append(name + ".png")

    def check(name, value):
        assert value, name
        checks[name] = True

    try:
        wait(lambda: not window.library.scanning)
        # Recent items request thumbnails without making the user visit the library.
        wait(lambda: window.download_page.recent.count() == 3 and all(
            window.download_page.recent.item(i).data(RecentDelegate.Row).get("thumb") for i in range(3)))
        checks["recent_thumbnails_load_on_home"] = True
        window.download_page.render_recent(window.store.rows())
        shot("download")
        check("icon_rail_without_text_labels", window.icon_rail.isVisible() and window.icon_rail.width() == RAIL["width"] and all(not button.text() for button in window.rail_navigation.values()) and window.menu_button.menu() is None)
        check("rail_controls_have_full_targets", all(button.height() >= RAIL["button_size"] for button in window.rail_navigation.values()))
        check("idle_task_hidden", not window.download_page.task_panel.isVisible())
        visible_texts = [label.text() for label in window.findChildren(QLabel) if label.isVisible() and label.text()]
        check("home_has_only_requested_copy", visible_texts == [window.download_page.greeting.text()])
        check("chrome_is_monochrome", all(color[1:3] == color[3:5] == color[5:7] for color in COLORS.values()))
        send = window.download_page.submit.grab()
        check("submit_button_is_black", send.toImage().pixelColor(round(6 * send.devicePixelRatioF()), round(21 * send.devicePixelRatioF())).name() == COLORS["accent"])
        rects = [window.download_page.recent.visualItemRect(window.download_page.recent.item(i)) for i in range(3)]
        check("three_home_previews_share_one_row", len({rect.y() for rect in rects}) == 1 and all(rect.width() > 150 for rect in rects))
        QTest.mouseClick(window.menu_button, Qt.LeftButton)
        QTest.qWait(100)
        check("logo_expands_full_height_sidebar", window.icon_rail.expanded and window.icon_rail.width() == RAIL["expanded_width"] and window.icon_rail.height() == window.central.height() and app.activePopupWidget() is None)
        check("expanded_sidebar_has_navigation_and_real_history", all(button.text() for button in window.rail_navigation.values()) and window.icon_rail.recent.count() == 3)
        check("expanded_home_keeps_composer_in_bounds", window.download_page.composer.width() <= window.pages.width())
        shot("sidebar-expanded")
        QTest.mouseClick(window.rail_navigation[1], Qt.LeftButton)
        window.library.search.setText("手写")
        QTest.mouseClick(window.icon_rail.header_search, Qt.LeftButton)
        QTest.qWait(100)
        search = window.search_dialog
        check("search_is_an_independent_overlay", search.isVisible() and search.search.hasFocus() and window.pages.currentIndex() == 1 and window.library.search.text() == "手写")
        QTest.keyClick(search.search, Qt.Key_Down)
        check("search_arrow_keys_navigate_results", search.results.currentRow() == 1 and search.search.hasFocus())
        shot("search", search)
        search.search.setText("朋友")
        check("search_filters_real_titles_without_changing_library", search.results.count() == 1 and window.library.search.text() == "手写")
        shot("search-results", search)
        search.search.setText("不会匹配的作品名称")
        check("search_empty_state", search.results.count() == 0 and search.stack.currentWidget() is search.empty)
        shot("search-no-results", search)
        QTest.keyClick(search.search, Qt.Key_Escape)
        check("escape_returns_to_original_page_and_filter", not search.isVisible() and window.pages.currentIndex() == 1 and window.library.search.text() == "手写")
        QTest.mouseClick(window.icon_rail.header_search, Qt.LeftButton)
        search.search.setText("朋友")
        QTest.keyClick(search.search, Qt.Key_Return)
        wait(lambda: window.player_dialog is not None and window.player_dialog.video.image is not None)
        check("search_enter_opens_real_media", not search.isVisible() and not window.player_dialog.video.image.isNull())
        window.player_dialog.close()
        window.player_dialog = None
        window.library.search.clear()
        QTest.mouseClick(window.icon_rail.collapse_button, Qt.LeftButton)
        check("collapse_restores_icon_rail_and_keeps_selection", not window.icon_rail.expanded and window.icon_rail.width() == RAIL["width"] and window.rail_navigation[1].isChecked())
        wait(lambda: not window.library.scanning)
        for page in (2, 0, 1):
            QTest.mouseClick(window.rail_navigation[page], Qt.LeftButton)
            check(f"rail_opens_page_{page}", window.pages.currentIndex() == page and window.rail_navigation[page].isChecked())
        window.activateWindow()
        window.library.grid.setFocus()
        QTest.qWait(60)
        QTest.keyClick(window, Qt.Key_K, Qt.ControlModifier)
        check("collapsed_rail_omits_search_and_shortcut_still_works", not window.icon_rail.header_search.isVisible() and len(window.rail_navigation) == 3 and window.search_dialog.isVisible() and sum(button.isChecked() for button in window.rail_navigation.values()) == 1)
        QTest.keyClick(window.search_dialog.search, Qt.Key_Escape)
        shot("library")
        grid = window.library.grid
        check("default_three_columns", len({grid.visualRect(grid.model().index(i)).x() for i in range(3)}) == 3)
        window.library.search.setText("没有匹配的关键词")
        check("no_results_has_recovery", window.library.results.currentWidget() is window.library.empty)
        shot("library-no-results")
        window.library.empty.button.click()
        check("clear_search_restores_library", not window.library.search.text() and window.library.model.rowCount() == 3)
        window.library.model.set_rows([])
        window.library._notice()
        shot("library-empty")
        window.library.empty.button.click()
        check("empty_library_navigates_to_download", window.pages.currentIndex() == 0)
        window.library.reload()
        window.set_page(2)
        shot("updates")
        QTest.mouseClick(window.account_button, Qt.LeftButton)
        QTest.qWait(100)
        check("bottom_account_opens_settings", window.settings_dialog is not None and window.settings_dialog.isVisible())
        check("settings_are_larger_and_resizable", window.settings_dialog.width() >= DIALOG["settings_width"] and window.settings_dialog.height() >= DIALOG["settings_height"] and window.settings_dialog.isSizeGripEnabled())
        shot("settings", window.settings_dialog)
        check("settings_source_and_done_fit", window.settings_dialog.source.geometry().right() < window.settings_dialog.width())
        window.settings_dialog.resize(DIALOG["settings_min_width"], DIALOG["settings_min_height"])
        QTest.qWait(100)
        check("settings_can_shrink_without_clipping", window.settings_dialog.width() == DIALOG["settings_min_width"] and window.settings_dialog.height() == DIALOG["settings_min_height"] and window.settings_dialog.source.isVisible())
        shot("settings-compact", window.settings_dialog)
        window.settings_dialog.close()
        window.show_logs()
        shot("diagnostics", window.log_dialog)
        window.log_dialog.close()
        window.set_page(0)
        first = window.store.rows()[0]
        task = SimpleNamespace(title=first["title"], state="running", message="正在下载视频和音频…",
                               total=160 * 1024 ** 2, downloaded=92 * 1024 ** 2, speed=4.8 * 1024 ** 2,
                               eta=14, cancelled=False, result=None)
        window.download_page.render(task)
        check("running_progress_and_cancel", window.download_page.progress.value() == 58 and window.download_page.cancel_button.isVisible())
        shot("download-running")
        task.state = "failed"
        task.message = "站点暂时无法访问。请检查网络后重试；需要账号权限的作品可以先完成网页登录。"
        window.download_page.render(task)
        check("failure_offers_retry_and_login", window.download_page.retry_button.isVisible() and window.download_page.login_button.isVisible())
        shot("download-failed")
        task.state, task.result = "done", {"duration": first["duration"], "size": first["size"]}
        task.message = "已保存到本地，可以打开观看。"
        window.download_page.render(task)
        check("done_has_library_action", window.download_page.progress.value() == 100 and window.download_page.view_button.isVisible())
        shot("download-complete")
        task.state, task.result = "cancelled", None
        task.title = "超长作品标题 · " * 40
        task.message = "下载已取消，可点击重试重新开始。"
        window.download_page.render(task)
        window.download_page.reject_input("没有识别到作品链接，请复制 Bilibili、抖音或 X 的分享链接再试。")
        window.resize(METRICS["min_width"], METRICS["min_height"])
        QTest.qWait(150)
        check("minimum_window_honored", window.width() == METRICS["min_width"] and window.height() == METRICS["min_height"])
        check("long_title_does_not_expand_window", window.download_page.task_title.width() < window.pages.width())
        shot("compact-download")
        check("composer_stays_within_window", window.download_page.composer.width() <= window.pages.width())
        window.set_page(1)
        wait(lambda: not window.library.scanning)
        QTest.qWait(100)
        check("compact_two_columns", len({grid.visualRect(grid.model().index(i)).x() for i in range(3)}) == 2)
        location = window.library.location_bar
        location.set_path("C:/" + "很长的文件夹名称/" * 30 + "视频")
        check("long_path_keeps_actions_visible", location.folder_button.isVisible() and location.folder_button.geometry().right() <= location.width())
        shot("compact-library")
        window.icon_rail.set_expanded(True)
        QTest.qWait(100)
        check("compact_expanded_sidebar_and_library_fit", window.width() == METRICS["min_width"] and window.pages.width() > 0 and window.library.folder_button.geometry().right() <= window.library.location_bar.width())
        shot("compact-sidebar")
        window.icon_rail.set_expanded(False)
        window.set_page(2)
        window.update_page.notes.setMarkdown("### 界面状态预览\n\n这是本地检查使用的示例内容。\n\n- 下载进度和安装操作\n- 较长的更新说明会在这里滚动显示。")
        window.update_page.transfer_panel.show()
        window.update_page.transfer_title.setText("更新包已下载（界面示例）")
        window.update_page.progress.setRange(0, 100)
        window.update_page.progress.setValue(100)
        window.update_page.stats.setText("48.0 MB / 48.0 MB · 100%")
        window.update_page.transfer_message.setText("安装包已准备就绪。安装前需要确认退出软件。")
        window.update_page.install_button.show()
        shot("compact-update-ready")
        check("compact_update_action_visible", window.update_page.install_button.isVisible())
        window.resize(1440, 900)
        window.set_page(1)
        wait(lambda: not window.library.scanning)
        shot("wide-library")
        # The real recent-row action opens the native media player.
        window.resize(METRICS["default_width"], METRICS["default_height"])
        window.set_page(0)
        window.download_page.input_message.hide()
        window.download_page.recent.setCurrentRow(0)
        window.download_page.recent.setFocus()
        QTest.keyClick(window.download_page.recent, Qt.Key_Return)
        wait(lambda: window.player_dialog is not None and window.player_dialog.video.image is not None)
        window.player_dialog.player.pause()
        check("recent_row_opens_decoded_media", not window.player_dialog.video.image.isNull())
        shot("player", window.player_dialog)
        window.player_dialog.close()
        window.player_dialog = None
        assets = [{"kind": "image", "path": row["thumb"]} for row in window.store.rows() if row["thumb"]]
        # Gallery paths are resolved by basename inside a dedicated copy folder.
        gallery_folder = directory / "gallery-fixture"
        gallery_folder.mkdir(exist_ok=True)
        for asset in assets:
            shutil.copy2(asset["path"], gallery_folder / Path(asset["path"]).name)
        gallery = GalleryDialog({"title": "图文作品 · 界面预览", "path": str(gallery_folder),
                                 "metadata": json.dumps({"assets": assets})}, window)
        gallery.show()
        shot("gallery", gallery)
        gallery.close()
        report = {"passed": True, "checks": checks, "scale": app.devicePixelRatio(),
                  "source": "real Qt widgets; copied local media; illustrative task states only in capture mode",
                  "published": False, "screenshots": sorted(screenshots)}
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({**report, "directory": str(directory)}, ensure_ascii=False))
    finally:
        window.install_exit = True
        window.close()
        wait(lambda: not window._jobs_running())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--scale", default="1", choices=("1", "1.5", "2"))
    parser.add_argument("--page", type=int, default=0, choices=(0, 1, 2))
    parser.add_argument("--snapshot-on-start", action="store_true")
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--work-dir", type=Path, help="Use a separate local review directory")
    args = parser.parse_args()
    if args.capture:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = args.scale
    work = ROOT / "build" / ("ui-review/scale-" + args.scale if args.capture else "ui-preview")
    if args.work_dir:
        work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    os.environ["LOCALAPPDATA"] = str(work / "preferences")
    output = work / "示例视频"
    os.environ.pop("VIDEO_DOWNLOADER_OUTPUT", None)
    from runtime_paths import read_settings, save_settings
    if read_settings().get("output"):
        output = Path(read_settings()["output"])
    else:
        save_settings(output=str(output))

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication
    from app import DownloadWindow
    from desktop_verify import prepare_fonts
    from media_library import LibraryStore
    from runtime_paths import configure_tools

    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv[:1])
    configure_tools()
    prepare_fonts()
    store = LibraryStore()
    seed_samples(store, output)
    window = DownloadWindow(auto_scan=False, restore_web_login=False, check_updates=False, store=store)
    window.setWindowTitle("视频下载器 · 设计预览")
    window.show()
    window.set_page(args.page)
    if args.expanded:
        window.icon_rail.set_expanded(True)
    if args.capture:
        capture_review(app, window, work)
        return 0
    if args.snapshot_on_start:
        QTimer.singleShot(1200, lambda: window.grab().save(str(work / "interactive-start.png")))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
