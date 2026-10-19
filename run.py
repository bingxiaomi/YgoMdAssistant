"""Run from any working directory, including before editable installation."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ygo_assistant.app import main

if __name__ == "__main__":
    raise SystemExit(main(["--config", str(ROOT / "configs" / "app.yaml"), *sys.argv[1:]]))
