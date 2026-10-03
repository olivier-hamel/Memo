"""Start and stop the Python and Vite development servers together."""
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    processes = []

    def stop(_signum=None, _frame=None):
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT))
        # Run Vite directly so terminating the launcher also terminates its child.
        processes.append(subprocess.Popen(
            ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1"], cwd=ROOT / "frontend"))
        print("Mémo : http://localhost:5173\nAPI : http://localhost:8000/docs\nCtrl+C pour arrêter.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(.3)
        return next((process.returncode for process in processes if process.returncode is not None), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        stop()


if __name__ == "__main__":
    sys.exit(main())
