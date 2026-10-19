import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ygo_assistant.app import main
from ygo_assistant.bootstrap import AppConfig
from ygo_assistant.ui.main_window import MainWindow


def test_check_command(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text("log_directory: logs\n", encoding="utf-8")
    assert main(["--config", str(path), "--check"]) == 0
    assert (tmp_path / "logs" / "assistant.log").exists()


def test_window_offscreen():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(AppConfig())
    window.show()
    app.processEvents()
    assert window.isVisible()
    assert window.windowTitle() == "YGO Tactical Assistant"
    window.close()
