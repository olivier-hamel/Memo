"""MongoDB card sets with immutable card versions and atomic editor updates."""
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path

from bson import BSON
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .study_engine import StudySession

DEFAULT_SET_ID = "default-ethics"
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024


class DeckError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def valid_id(value):
    if value != DEFAULT_SET_ID and not re.fullmatch(r"[a-f0-9]{32}", value):
        raise DeckError(404, "Ensemble introuvable.")
    return value


def validate_cards(cards):
    if not isinstance(cards, list) or not 1 <= len(cards) <= 300:
        raise DeckError(400, "Un ensemble doit contenir entre 1 et 300 cartes.")
    pairs = []
    for card in cards:
        if (not isinstance(card, dict) or set(card) != {"term", "definition"}
                or not isinstance(card["term"], str) or not card["term"].strip()
                or not isinstance(card["definition"], str) or not card["definition"].strip()
                or len(card["term"]) > 2000 or len(card["definition"]) > 12000):
            raise DeckError(400, "Chaque carte doit avoir une question et une réponse valides.")
        pairs.append((card["term"], card["definition"]))
    if len(set(pairs)) != len(pairs):
        raise DeckError(400, "Deux cartes identiques sont présentes dans cet ensemble.")
    return pairs


class MongoDecks:
    def __init__(self, collection, client=None):
        self.collection, self.client = collection, client

    @classmethod
    def from_env(cls):
        uri = os.environ.get("MEMO_MONGODB_URI", "").strip()
        filename = os.environ.get("MEMO_MONGODB_URI_FILE")
        if filename:
            try:
                uri = Path(filename).read_text().strip()
            except OSError:
                raise DeckError(503, "La configuration MongoDB n’est pas accessible.") from None
        if not uri:
            return None
        name = os.environ.get("MEMO_MONGODB_DATABASE", "memo")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", name):
            raise DeckError(503, "Le nom de la base MongoDB est invalide.")
        try:
            client = MongoClient(uri, appname="Memo", serverSelectionTimeoutMS=5000,
                                 connectTimeoutMS=5000, socketTimeoutMS=5000)
            return cls(client[name]["memo_card_sets"], client)
        except (PyMongoError, ValueError):
            raise DeckError(503, "La configuration MongoDB est invalide.") from None

    def close(self):
        if self.client is not None:
            self.client.close()

    def _run(self, operation):
        try:
            return operation()
        except PyMongoError:
            # Driver errors can contain database addresses; keep them out of responses.
            raise DeckError(503, "La bibliothèque est momentanément indisponible. Réessaie dans un instant.") from None

    def _find(self, user, identifier):
        valid_id(identifier)
        document = self._run(lambda: self.collection.find_one({"_id": identifier,
            "$or": [{"owner_id": user["id"]}, {"shared": True}]}))
        if document is None:
            raise DeckError(404, "Ensemble introuvable.")
        return document

    @staticmethod
    def summary(document, user):
        return dict(id=document["_id"], title=document["title"], description=document["description"],
                    editable=document["owner_id"] == user["id"], shared=document["shared"],
                    revision=document["revision"], latest_version=document["latest_version"],
                    versions=[dict(version=v["version"], card_count=v["card_count"]) for v in document["versions"]])

    def list(self, user):
        documents = self._run(lambda: list(self.collection.find({
            "$or": [{"owner_id": user["id"]}, {"shared": True}]}, {"versions.cards": 0}).sort("updated_at", -1)))
        return [self.summary(d, user) for d in documents]

    def get(self, user, identifier, version=None):
        document = self._find(user, identifier)
        version = document["latest_version"] if version is None else version
        selected = next((v for v in document["versions"] if v["version"] == version), None)
        if selected is None:
            raise DeckError(404, "Version introuvable.")
        return {**self.summary(document, user), "version": version, "cards": selected["cards"]}

    def save(self, user, title, description, cards, identifier=None, revision=None):
        title, description = title.strip(), description.strip()
        if not 1 <= len(title) <= 100 or len(description) > 1000:
            raise DeckError(400, "Vérifie le titre et la description de l’ensemble.")
        validate_cards(cards)
        now = time.time()
        new_revision = secrets.token_hex(16)
        if identifier is None:
            if self._run(lambda: self.collection.count_documents({"owner_id": user["id"]})) >= 100:
                raise DeckError(400, "La bibliothèque contient déjà 100 ensembles personnels.")
            document = dict(_id=uuid.uuid4().hex, owner_id=user["id"], shared=False,
                title=title, description=description, revision=new_revision, latest_version=1,
                versions=[dict(version=1, cards=cards, card_count=len(cards))], created_at=now, updated_at=now)
            if len(BSON.encode(document)) > MAX_DOCUMENT_BYTES:
                raise DeckError(400, "Cet ensemble est trop volumineux.")
            self._run(lambda: self.collection.insert_one(document))
            return self.get(user, document["_id"])
        document = self._find(user, identifier)
        if document["owner_id"] != user["id"]:
            raise DeckError(403, "Seule la personne qui a créé cet ensemble peut le modifier.")
        if document["revision"] != revision:
            raise DeckError(409, "Cet ensemble a changé dans un autre onglet. Recharge-le avant de modifier.")
        latest = document["versions"][-1]
        if cards != latest["cards"]:
            document["latest_version"] += 1
            document["versions"].append(dict(version=document["latest_version"], cards=cards, card_count=len(cards)))
        document.update(title=title, description=description, revision=new_revision, updated_at=now)
        if len(BSON.encode(document)) > MAX_DOCUMENT_BYTES:
            raise DeckError(400, "L’historique de cet ensemble est plein. Crée une copie pour poursuivre.")
        result = self._run(lambda: self.collection.replace_one(
            {"_id": identifier, "owner_id": user["id"], "revision": revision}, document))
        if result.modified_count != 1:
            raise DeckError(409, "Cet ensemble a changé dans un autre onglet. Recharge-le avant de modifier.")
        return self.get(user, identifier)

    def import_default(self, owner):
        cards = json.loads((Path(__file__).parent / "data" / "flashcards.json").read_text())
        source = [dict(term=t, definition=d) for t, d in cards]
        validate_cards(source)
        # Preserve exact content and IDs, and never replace an edited imported set.
        now = time.time()
        document = dict(_id=DEFAULT_SET_ID, owner_id=owner["id"], shared=True,
            title="Éthique de l’ingénieur", description="L’ensemble d’origine de Mémo.",
            revision=secrets.token_hex(16), latest_version=1,
            versions=[dict(version=1, cards=source, card_count=len(source))], created_at=now, updated_at=now)
        self._run(lambda: self.collection.update_one({"_id": DEFAULT_SET_ID}, {"$setOnInsert": document}, upsert=True))
        existing = self.get(owner, DEFAULT_SET_ID, 1)
        if StudySession(validate_cards(existing["cards"])).study_set_id != StudySession(cards).study_set_id:
            raise DeckError(409, "L’ensemble importé ne correspond pas à la sauvegarde d’origine.")


if __name__ == "__main__":
    import argparse
    from .auth import Accounts
    parser = argparse.ArgumentParser(description="Importer l’ensemble d’origine dans MongoDB sans écraser les données.")
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    repository = None
    try:
        repository = MongoDecks.from_env()
        if repository is None:
            raise DeckError(503, "Configure MongoDB avant l’import.")
        owner = Accounts(os.environ.get("FLASHCARD_WEB_DATA", "backend/data")).user(args.owner)
        repository.import_default(owner)
        print("Ensemble d’origine prêt. Les cartes, versions et progrès existants sont conservés.")
    except (DeckError, ValueError) as error:
        print(str(error))
        raise SystemExit(1)
    finally:
        if repository is not None:
            repository.close()
