"""Hosting entry point, including when the project is unpacked directly to /app."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().with_name('bot.py')), run_name='__main__')
