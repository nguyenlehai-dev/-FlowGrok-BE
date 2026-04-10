from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


def test_app_imports():
    assert main.app.title == "FlowGrok API"
