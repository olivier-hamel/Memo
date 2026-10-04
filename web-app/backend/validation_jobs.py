"""Private, durable validation results with work independent of HTTP connections."""
import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

from .decks import DeckError

ACTIVE = {"queued", "running"}
RETENTION_SECONDS = 7 * 86400


class ValidationJobs:
    def __init__(self, directory, slots, requests, validate):
        self.directory = Path(directory) / "validation-jobs"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.slots, self.requests, self.validate = slots, requests, validate
        self.jobs, self.tasks = {}, {}
        for path in self.directory.glob("*.json"):
            try:
                job = json.loads(path.read_text())
                if job["updated_at"] < time.time() - RETENTION_SECONDS:
                    path.unlink()
                    continue
                if job["status"] in ACTIVE:
                    job.update(status="failed", error="Le serveur a redémarré pendant la validation. Réessaie pour reprendre les étapes conservées.", unread=True)
                    self.write(job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def write(self, job):
        job["updated_at"] = time.time()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False, encoding="utf-8") as output:
                temporary = Path(output.name)
                json.dump(job, output, ensure_ascii=False)
            os.replace(temporary, self.directory / f'{job["id"]}.json')
        except OSError:
            raise DeckError(503, "La validation ne peut pas être sauvegardée. Réessaie dans un instant.") from None
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def summary(job):
        return {key: job[key] for key in ("id", "title", "set_id", "draft_id", "status", "progress", "error", "unread", "created_at", "updated_at")}

    def list(self, owner):
        return [self.summary(job) for job in sorted(self.jobs.values(), key=lambda job: job["created_at"], reverse=True)
                if job["owner"] == owner and job["updated_at"] >= time.time() - RETENTION_SECONDS][:20]

    def get(self, owner, identifier):
        job = self.jobs.get(identifier)
        if not job or job["owner"] != owner:
            raise DeckError(404, "Validation introuvable.")
        return job

    def start(self, owner, snapshot, documents):
        for job in self.jobs.values():
            if job["owner"] == owner and job["status"] in ACTIVE:
                if job["snapshot"] == snapshot:
                    return self.summary(job)
                raise DeckError(409, "Une validation est déjà en cours dans ton espace. Attends son résultat avant d’en lancer une autre.")
        if len(self.tasks) >= 20:
            raise DeckError(503, "Les validations sont occupées. Réessaie dans un instant.")
        job = dict(id=uuid.uuid4().hex, owner=owner, title=snapshot["title"], set_id=snapshot["set_id"],
                   draft_id=snapshot["draft_id"], snapshot=snapshot,
                   documents=[{key: document[key] for key in ("id", "name", "kind", "page_count")} for document in documents],
                   status="queued", progress="En attente…", error="", unread=False, result=None, created_at=time.time(), updated_at=time.time())
        self.write(job)
        self.jobs[job["id"]] = job
        # Keep only the recent history for each account; active tasks are always retained.
        old = sorted((item for item in self.jobs.values() if item["owner"] == owner and item["status"] not in ACTIVE),
                     key=lambda item: item["created_at"], reverse=True)[19:]
        for item in old:
            (self.directory / f'{item["id"]}.json').unlink(missing_ok=True)
            self.jobs.pop(item["id"], None)
        task = asyncio.create_task(self.run(job, documents))
        self.tasks[job["id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(job["id"], None))
        return self.summary(job)

    async def run(self, job, documents):
        try:
            async with self.slots:
                def progress(message):
                    job.update(status="running", progress=message)
                    self.write(job)
                progress("Préparation des documents…")
                result = await self.validate(job["snapshot"]["cards"], documents,
                    cache_directory=self.directory.parent / "validation-cache", requests=self.requests, progress=progress)
                if (result.get("checked_pages") != sum(document["page_count"] for document in documents)
                        or result.get("checked_cards") != len(job["snapshot"]["cards"])
                        or not isinstance(result.get("covered"), bool) or not isinstance(result.get("proposals"), list)
                        or result["covered"] != (len(result["proposals"]) == 0)):
                    raise DeckError(422, "Tous les documents et toutes les cartes n’ont pas été vérifiés. Réessaie.")
                job.update(status="completed", progress="Validation terminée", result=result, unread=True)
        except asyncio.CancelledError:
            job.update(status="failed", error="La validation a été interrompue. Réessaie pour reprendre les étapes conservées.", unread=True)
            raise
        except DeckError as error:
            job.update(status="failed", error=str(error), unread=True)
        except Exception:
            logging.getLogger(__name__).exception("Background validation failed")
            job.update(status="failed", error="La validation a échoué. Les étapes terminées sont conservées ; réessaie.", unread=True)
        finally:
            self.write(job)

    def acknowledge(self, owner, identifier):
        job = self.get(owner, identifier)
        job["unread"] = False
        self.write(job)
        return self.summary(job)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
