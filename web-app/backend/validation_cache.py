"""Private, content-addressed checkpoints; never cache credentials or remote file URLs."""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


class ValidationCache:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else None
        self.max_age = 30 * 86400
        if self.directory:
            try:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                for path in self.directory.glob("*.json"):
                    try:
                        if time.time() - path.stat().st_mtime > self.max_age:
                            path.unlink()
                    except OSError:
                        pass
            except OSError:
                self.directory = None

    @staticmethod
    def key(model, instructions, context):
        value = json.dumps({"version": 1, "model": model, "instructions": instructions,
            "context": context}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()

    def get(self, key, result_type):
        if not self.directory:
            return None
        path = self.directory / (key + ".json")
        try:
            if time.time() - path.stat().st_mtime > self.max_age:
                path.unlink()
                return None
            result = result_type.model_validate_json(path.read_text(encoding="utf-8"))
            return result if result.analysis_complete else None
        except (OSError, ValueError):
            return None

    def put(self, key, result):
        if not self.directory:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                    prefix="checkpoint-", delete=False) as output:
                temporary = Path(output.name)
                output.write(result.model_dump_json())
            os.replace(temporary, self.directory / (key + ".json"))
        except OSError:
            pass  # Cache availability must not alter the coverage result.
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def discard(self, key):
        if self.directory:
            try:
                (self.directory / (key + ".json")).unlink(missing_ok=True)
            except OSError:
                pass
