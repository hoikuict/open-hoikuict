"""Gracefully stoppable application process used by the restore gateway."""
from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
from windows_setup.worker import run_application

if __name__ == "__main__":
    run_application(int(sys.argv[1]))
