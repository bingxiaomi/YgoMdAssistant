import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QSlider, QSplitter,
                               QVBoxLayout, QWidget)

from ..bootstrap import AppConfig
from ..capture.frame_pipeline import FramePipeline
from ..capture.snapshot import save_snapshot
from ..capture.video_capture import VideoCapture
from ..capture.windows import list_windows
from ..vision.region_manager import default_profile, load_profile, save_profile
from .frame_view import FrameView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.pipeline = None
        self.frame = None
        self.playing = False
        self._last_error = None
        self._last_status = None
        self._dirty = False
        self.profile_path = config.regions_path
        self.profile = default_profile()
        startup_error = None
        if self.profile_path.exists():
            try:
                self.profile = load_profile(self.profile_path)
                if not {"duel_log", "effect_text"}.issubset(self.profile.regions):
                    raise ValueError("布局缺少 duel_log 或 effect_text")
            except (OSError, ValueError) as exc:
                self.profile = default_profile()
                startup_error = f"ROI 配置加载失败，使用默认布局：{exc}"
        self.setWindowTitle(config.title)
        self.resize(1360, 900)
        root = QWidget()
        layout = QVBoxLayout(root)
        sources = QHBoxLayout()
        self.window_selector = QComboBox()
        self.window_selector.setMinimumWidth(320)
        sources.addWidget(self.window_selector, 1)
        self._button(sources, "刷新窗口", self.refresh_windows)
        self._button(sources, "开始实时采集", self.start_live)
        self._button(sources, "停止", self.stop_capture)
        self._button(sources, "导入录像…", self.import_video)
        layout.addLayout(sources)
        self.notice = QLabel("原生窗口采集：后台或被其他窗口遮挡时仍可取帧；预览缩放不影响原始图像与 ROI。")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        split = QSplitter()
        self.preview = FrameView()
        self.preview.profile = self.profile
        self.preview.region_changed.connect(self._region_changed)
        split.addWidget(self.preview)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.addWidget(QLabel("ROI 校准 · 实时与录像共用"))
        self.region_selector = QComboBox()
        self._populate_regions()
        self.region_selector.currentIndexChanged.connect(self._select_region)
        self._select_region()
        side.addWidget(self.region_selector)
        self._button(side, "框选 / 重画选中区域", self.draw_region)
        hint = QLabel("拖动框内可移动；拖动右下角可缩放。\n点击上方按钮后拖拽可重新框选。")
        hint.setWordWrap(True)
        side.addWidget(hint)
        overlays = QCheckBox("显示 ROI 框")
        overlays.setChecked(True)
        self.overlay_checkbox = overlays
        overlays.toggled.connect(self._toggle_regions)
        side.addWidget(overlays)
        profile_actions = QHBoxLayout()
        self._button(profile_actions, "保存 ROI", self.save_regions)
        self._button(profile_actions, "另存为…", self.save_regions_as)
        self._button(profile_actions, "加载…", self.load_regions)
        side.addLayout(profile_actions)
        self.profile_label = QLabel()
        self.profile_label.setWordWrap(True)
        side.addWidget(self.profile_label)
        self.crop_views = {}
        for name, title in (("duel_log", "决斗日志裁剪预览"), ("effect_text", "效果描述裁剪预览")):
            side.addWidget(QLabel(title))
            view = FrameView(editable=False)
            view.placeholder = "等待画面"
            self.crop_views[name] = view
            side.addWidget(view, 1)
        split.addWidget(sidebar)
        split.setSizes([950, 370])
        layout.addWidget(split, 1)
        playback = QHBoxLayout()
        self.play_button = self._button(playback, "播放", self.toggle_play)
        self.previous_button = self._button(playback, "上一帧", lambda: self.step(-1))
        self.next_button = self._button(playback, "下一帧", lambda: self.step(1))
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderPressed.connect(self._pause_video)
        self.seek_slider.sliderReleased.connect(self._seek_released)
        playback.addWidget(self.seek_slider, 1)
        self.time_label = QLabel("00:00.000")
        playback.addWidget(self.time_label)
        self._button(playback, "保存当前帧及 ROI", self.snapshot)
        layout.addLayout(playback)
        self.frame_label = QLabel("尚未连接采集源")
        layout.addWidget(self.frame_label)
        self.setCentralWidget(root)
        self._set_video_controls(False)
        self._update_profile_label()
        self.refresh_windows()
        self.statusBar().showMessage(startup_error or "就绪 · 选择窗口或导入录像")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_frames)
        self.timer.start(round(1000 / config.preview_fps))
        for sequence, callback in (("Space", self.toggle_play), ("Left", lambda: self.step(-1)),
                                   ("Right", lambda: self.step(1)), ("Ctrl+S", self.save_regions)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    @staticmethod
    def _button(layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def refresh_windows(self):
        previous = self.window_selector.currentData()
        self.window_selector.clear()
        try:
            for window in list_windows():
                self.window_selector.addItem(f"{window.title}  [PID {window.pid}]", window.hwnd)
            index = self.window_selector.findData(previous)
            if index >= 0:
                self.window_selector.setCurrentIndex(index)
        except Exception as exc:
            self.statusBar().showMessage(str(exc))

    def start_live(self):
        hwnd = self.window_selector.currentData()
        if hwnd is None:
            self._error("请先打开游戏并刷新窗口列表")
            return
        from ..capture.factory import create_live_capture
        title = self.window_selector.currentText()
        if self._start_pipeline(lambda: create_live_capture(hwnd, backend=self.config.capture_backend,
                                                          fps=self.config.capture_fps), live=True):
            detail = "原生客户区，无缩放；支持后台与遮挡，最小化时等待还原" if self.config.capture_backend == "wgc" else "屏幕可见区域；请保持游戏可见并避免遮挡"
            self.notice.setText(f"{self.config.capture_backend.upper()} · {title} · {detail}")

    def import_video(self):
        filename, _ = QFileDialog.getOpenFileName(self, "导入对局录像", "", "录像 (*.mp4 *.mkv *.avi *.mov *.webm);;所有文件 (*)")
        if filename:
            self.open_video(Path(filename))

    def open_video(self, path: Path):
        if self._start_pipeline(lambda: VideoCapture(path), live=False):
            self.notice.setText(f"录像 · {path.name}。已暂停，可逐帧校准；与实时模式共用当前 ROI 配置。")

    def _start_pipeline(self, factory, *, live):
        if not self.stop_capture():
            return False
        self.frame = None
        self.preview.set_image(None)
        for view in self.crop_views.values():
            view.set_image(None)
        self._last_error = self._last_status = None
        self._set_video_controls(not live)
        self.seek_slider.setRange(0, 0)
        self.pipeline = FramePipeline(factory, live=live, capture_fps=self.config.capture_fps,
                                      capacity=self.config.frame_queue_size)
        self.pipeline.start()
        self.statusBar().showMessage("正在连接输入源…")
        return True

    def stop_capture(self):
        if self.pipeline is not None:
            self.pipeline.request_stop()
            if not self.pipeline.join(1):
                self.statusBar().showMessage("采集源正在退出，请稍后再试")
                return False
            self.pipeline = None
        self.playing = False
        self.play_button.setText("播放")
        self._set_video_controls(False)
        self.statusBar().showMessage("已停止；当前画面已冻结")
        return True

    def _set_video_controls(self, enabled):
        for widget in (self.play_button, self.previous_button, self.next_button, self.seek_slider):
            widget.setEnabled(enabled)

    def _pause_video(self):
        if self.pipeline is not None and not self.pipeline.live:
            self.pipeline.set_paused(True)
            self.playing = False
            self.play_button.setText("播放")

    def toggle_play(self):
        if self.pipeline is None or self.pipeline.live or not self.pipeline.alive:
            return
        self.playing = not self.playing
        if self.playing and self.frame is not None and self.frame.frame_id >= self.pipeline.status.frame_count - 1:
            self.pipeline.seek_frame(0)
        self.pipeline.set_paused(not self.playing)
        self.play_button.setText("暂停" if self.playing else "播放")

    def step(self, delta):
        if self.pipeline is None or self.pipeline.live or self.frame is None:
            return
        self._pause_video()
        self.pipeline.seek_frame(self.frame.frame_id + delta)

    def _seek_released(self):
        if self.pipeline is not None and not self.pipeline.live:
            self._pause_video()
            self.pipeline.seek_frame(self.seek_slider.value())

    def poll_frames(self):
        if self.pipeline is None:
            return
        status = self.pipeline.status
        if status.error:
            if status.error != self._last_error:
                self._last_error = status.error
                self._pause_video()
                self._set_video_controls(False)
                self.notice.setText(f"输入已停止，画面已冻结：{status.error}")
                self.statusBar().showMessage(status.error)
            return
        if status.message != self._last_status:
            self._last_status = status.message
            self.statusBar().showMessage(status.message)
            if "播放结束" in status.message:
                self._pause_video()
        frame = self.pipeline.frames.latest()
        if frame is None:
            return
        self.frame = frame
        self.preview.set_image(frame.image)
        self._update_crops()
        if not self.pipeline.live:
            self.seek_slider.setRange(0, max(0, status.frame_count - 1))
            if not self.seek_slider.isSliderDown():
                self.seek_slider.setValue(frame.frame_id)
        minutes, seconds = divmod(frame.timestamp_ms / 1000, 60)
        self.time_label.setText(f"{int(minutes):02d}:{seconds:06.3f}")
        self.frame_label.setText(
            f"{frame.capture_backend or frame.source} · 原始 {frame.width} × {frame.height} · 帧 {frame.frame_id} · "
            f"{frame.timestamp_ms} ms · 读取 {status.capture_ms:.1f} ms · "
            f"队列 {len(self.pipeline.frames)}/{self.config.frame_queue_size} · 跳过 {self.pipeline.frames.dropped} 帧")

    def _populate_regions(self):
        self.region_selector.clear()
        for name, region in self.profile.regions.items():
            self.region_selector.addItem(region.label, name)

    def _select_region(self):
        self.preview.selected = self.region_selector.currentData()
        self.preview.update()

    def draw_region(self):
        self.overlay_checkbox.setChecked(True)
        self.preview.force_draw = True
        self.statusBar().showMessage("在主画面按住鼠标左键拖拽，框选当前选中的 ROI")

    def _toggle_regions(self, visible):
        self.preview.show_regions = visible
        self.preview.update()

    def _region_changed(self, name, region):
        self._dirty = True
        self._update_profile_label()
        self._update_crops()

    def _update_crops(self):
        if self.frame is not None:
            crops = self.profile.crops(self.frame)
            for name, view in self.crop_views.items():
                view.set_image(crops.get(name))

    def _update_profile_label(self):
        self.profile_label.setText(f"{'未保存 · ' if self._dirty else ''}{self.profile_path.name}\n"
                                   f"参考 {self.profile.reference_width}×{self.profile.reference_height}；坐标按画面比例缩放")

    def _save_profile(self, path):
        try:
            if self.frame is not None:
                self.profile.reference_width = self.frame.width
                self.profile.reference_height = self.frame.height
            save_profile(self.profile, path)
            self.profile_path = path
            self._dirty = False
            self._update_profile_label()
            self.statusBar().showMessage(f"ROI 已保存：{path}")
            return True
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return False

    def save_regions(self):
        return self._save_profile(self.profile_path)

    def save_regions_as(self):
        filename, _ = QFileDialog.getSaveFileName(self, "另存 ROI 布局", str(self.profile_path), "YAML (*.yaml)")
        if filename:
            self._save_profile(Path(filename))

    def load_regions(self):
        if not self._confirm_dirty():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "加载 ROI 布局", str(self.profile_path.parent), "YAML (*.yaml *.yml)")
        if not filename:
            return
        try:
            profile = load_profile(Path(filename))
            if not {"duel_log", "effect_text"}.issubset(profile.regions):
                raise ValueError("ROI 布局必须包含 duel_log 和 effect_text")
            self.profile = profile
            self.profile_path = Path(filename)
            self.preview.profile = profile
            self._dirty = False
            self._populate_regions()
            self._select_region()
            self._update_crops()
            self._update_profile_label()
            self.preview.update()
        except (OSError, ValueError) as exc:
            self._error(str(exc))

    def snapshot(self):
        if self.frame is None:
            self._error("尚无可保存的画面")
            return
        try:
            path = save_snapshot(self.frame, self.profile, self.config.snapshot_directory)
            self.statusBar().showMessage(f"原始帧、ROI 裁剪和元数据已保存：{path}")
        except (OSError, ValueError, RuntimeError) as exc:
            self._error(str(exc))

    def _error(self, message):
        logger.error("UI: %s", message)
        QMessageBox.warning(self, "无法完成操作", message)

    def _confirm_dirty(self):
        if not self._dirty:
            return True
        answer = QMessageBox.question(self, "保存 ROI", "当前 ROI 有未保存的修改，是否保存？",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return self.save_regions() if answer == QMessageBox.StandardButton.Save else True

    def closeEvent(self, event: QCloseEvent):
        if not self._confirm_dirty() or not self.stop_capture():
            event.ignore()
            return
        self.timer.stop()
        event.accept()
