"""Disposable editor browser fixture; never loads private connection settings."""
import atexit
import tempfile
from pathlib import Path

import mongomock

from backend.auth import Accounts
from backend.decks import MongoDecks
from backend.main import create_app
from backend.tests.document_fixtures import course_pdf, course_pptx
from fastapi.responses import FileResponse
from starlette.routing import Mount

directory = tempfile.TemporaryDirectory(prefix="memo-editor-e2e-")
atexit.register(directory.cleanup)
accounts = Accounts(directory.name)
owner = accounts.create("browser_oli", "Validation Oli", "browser-test-passphrase-123", must_change=False)
accounts.create("browser_max", "Validation Max", "browser-test-passphrase-123", must_change=False)
repository = MongoDecks(mongomock.MongoClient().memo.memo_card_sets)
repository.import_default(owner)
app = create_app(auth_enabled=True, require_https=False, data_dir=directory.name, deck_repository=repository)

course_pdf(Path(directory.name) / "Chapitre.pdf")
course_pptx(Path(directory.name) / "Cours.pptx", annotations=True)


@app.get("/api/__fixtures/course.pdf")
def sample_pdf():
    return FileResponse(Path(directory.name) / "Chapitre.pdf")


@app.get("/api/__fixtures/course.pptx")
def sample_pptx():
    return FileResponse(Path(directory.name) / "Cours.pptx")


# create_app mounts the production frontend last. Keep that catch-all behind
# these test-only routes, including when a local production build exists.
app.router.routes[:] = [route for route in app.router.routes if not isinstance(route, Mount)] + [
    route for route in app.router.routes if isinstance(route, Mount)]
