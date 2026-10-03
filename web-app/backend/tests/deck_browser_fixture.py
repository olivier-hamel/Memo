"""Disposable editor browser fixture; never loads private connection settings."""
import atexit
import tempfile

import mongomock

from backend.auth import Accounts
from backend.decks import MongoDecks
from backend.main import create_app

directory = tempfile.TemporaryDirectory(prefix="memo-editor-e2e-")
atexit.register(directory.cleanup)
accounts = Accounts(directory.name)
owner = accounts.create("browser_oli", "Validation Oli", "browser-test-passphrase-123", must_change=False)
accounts.create("browser_max", "Validation Max", "browser-test-passphrase-123", must_change=False)
repository = MongoDecks(mongomock.MongoClient().memo.memo_card_sets)
repository.import_default(owner)
app = create_app(auth_enabled=True, require_https=False, data_dir=directory.name, deck_repository=repository)
