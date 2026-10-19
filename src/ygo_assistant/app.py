import argparse
import logging
from pathlib import Path

from .bootstrap import configure_logging, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YGO Tactical Assistant")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate configuration without starting Qt")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--video", type=Path, help="Open a recording, initially paused")
    source.add_argument("--window-title", help="Select exactly one matching visible window and start capture")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        configure_logging(config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    logging.getLogger(__name__).info("Startup mode=%s", config.mode)
    if args.check:
        print(config.model_dump_json(indent=2))
        return 0
    from .capture.windows import enable_dpi_awareness
    enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow

    app = QApplication([])
    window = MainWindow(config)
    window.show()
    if args.video:
        window.open_video(args.video)
    elif args.window_title:
        from .capture.windows import list_windows
        query = "".join(args.window_title.lower().split())
        matches = [item for item in list_windows() if query in "".join(item.title.lower().split())]
        if len(matches) != 1:
            parser.error(f"Expected one matching window, found {len(matches)}")
        window.window_selector.setCurrentIndex(window.window_selector.findData(matches[0].hwnd))
        window.start_live()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
