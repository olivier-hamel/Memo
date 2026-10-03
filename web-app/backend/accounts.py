"""Server administration: python -m backend.accounts --help."""
import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

from .auth import Accounts
from .controller import WebStudy


def main():
    parser = argparse.ArgumentParser(description="Administrer les comptes Mémo.")
    parser.add_argument("--data-dir", default=os.environ.get("FLASHCARD_WEB_DATA", "backend/data"))
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("username")
    create.add_argument("--display-name", required=True)
    create.add_argument("--generate-password", action="store_true")
    reset = commands.add_parser("reset-password")
    reset.add_argument("username")
    reset.add_argument("--generate-password", action="store_true")
    load = commands.add_parser("import-progress")
    load.add_argument("username")
    load.add_argument("source", type=Path)
    retrieve = commands.add_parser("credential-path")
    retrieve.add_argument("username")
    args = parser.parse_args()
    accounts = Accounts(args.data_dir)
    try:
        if args.command in ("create", "reset-password"):
            password = secrets.token_urlsafe(24) if args.generate_password else getpass.getpass("Mot de passe initial : ")
            if not args.generate_password and password != getpass.getpass("Confirmer : "):
                raise ValueError("Les mots de passe ne correspondent pas.")
            if args.command == "create":
                user = accounts.create(args.username, args.display_name, password)
            else:
                user = accounts.user(args.username)
                accounts.set_password(user["id"], password, must_change=True)
            if args.generate_password:
                directory = accounts.directory / "bootstrap"
                directory.mkdir(mode=0o700, exist_ok=True)
                path = directory / (user["id"] + ".txt")
                with open(path, "w", opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
                    file.write(password + "\n")
                print("Mot de passe temporaire conservé dans :", path)
            print("Compte prêt. Un nouveau mot de passe sera demandé à la connexion.")
        elif args.command == "credential-path":
            path = accounts.directory / "bootstrap" / (accounts.user(args.username)["id"] + ".txt")
            if not path.exists():
                raise ValueError("Aucun mot de passe temporaire conservé pour ce compte.")
            print(path)
        else:
            user = accounts.user(args.username)
            path = accounts.progress_path(user["id"])
            if path.exists():
                raise ValueError("La progression existe déjà ; import refusé pour préserver les acquis.")
            # Parse and validate before creating the user's save. No shared import.
            data = json.loads(args.source.read_text(encoding="utf-8"))
            from .study_engine import StudySession
            cards = json.loads((Path(__file__).parent / "data" / "flashcards.json").read_text(encoding="utf-8"))
            StudySession(cards).restore(data)
            WebStudy(path, args.source)
            print("Progression importée pour", user["username"])
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
