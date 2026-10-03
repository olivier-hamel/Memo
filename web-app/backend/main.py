"""FastAPI app with isolated study sessions; run one Uvicorn worker."""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .controller import DATA_DIR, LEGACY_PATH, InvalidAction, WebStudy
from .auth import Accounts, PASSWORDS, SESSION_SECONDS
from .decks import DEFAULT_SET_ID, DeckError, MongoDecks, validate_cards

COOKIE = "memo_session"


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["flip", "grade", "navigate", "typed", "mode", "settings", "reset", "refresh"]
    revision: str
    correct: StrictBool | None = None
    direction: StrictInt | None = None
    mode: Literal["LEARN"] | None = None
    response: str | None = None
    typed: StrictBool | None = None


class CardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=1, max_length=2000)
    definition: str = Field(min_length=1, max_length=12000)


class SetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    cards: list[CardInput] = Field(min_length=1, max_length=300)
    revision: str | None = Field(default=None, max_length=64)


def create_app(progress_path=None, legacy_path=LEGACY_PATH, raw_cards=None, config=None,
               auth_enabled=None, data_dir=None, require_https=None, clock=None, deck_repository=None):
    auth_enabled = auth_enabled if auth_enabled is not None else os.environ.get("FLASHCARD_WEB_AUTH", "0") == "1"
    require_https = require_https if require_https is not None else os.environ.get("FLASHCARD_WEB_REQUIRE_HTTPS", "1") != "0"
    directory = Path(data_dir or os.environ.get("FLASHCARD_WEB_DATA", str(DATA_DIR)))
    cookie_path = os.environ.get("MEMO_COOKIE_PATH", "/")
    if os.environ.get("MEMO_ENV") == "production" and (not auth_enabled or not require_https):
        raise RuntimeError("Production requires accounts and HTTPS.")

    @asynccontextmanager
    async def lifespan(app):
        app.state.lock = RLock()
        app.state.studies = {}
        app.state.decks = deck_repository if deck_repository is not None else MongoDecks.from_env()
        if auth_enabled:
            app.state.accounts = Accounts(directory, **({"clock": clock} if clock else {}))
        else:
            path = progress_path or os.environ.get("FLASHCARD_WEB_PROGRESS", str(DATA_DIR / "progress.json"))
            source = legacy_path if os.environ.get("FLASHCARD_WEB_IMPORT_DESKTOP", "1") != "0" else None
            app.state.study = WebStudy(path, source, raw_cards, config)
        try:
            yield
        finally:
            if deck_repository is None and app.state.decks is not None:
                app.state.decks.close()

    app = FastAPI(title="Mémo · Flashcard Learn", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.removeprefix(request.scope.get("root_path", "")).startswith("/api/"):
            if auth_enabled and not request.url.path.endswith("/api/health"):
                if require_https and request.url.scheme != "https":
                    return JSONResponse({"detail": "Une connexion HTTPS est nécessaire."}, status_code=426)
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    origin = request.headers.get("origin")
                    expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
                    if (origin != expected or request.headers.get("x-memo-request") != "1"
                            or request.headers.get("content-type", "").split(";")[0] != "application/json"):
                        return JSONResponse({"detail": "Requête refusée."}, status_code=403)
            if request.url.path.removeprefix(request.scope.get("root_path", "")).startswith("/api/sets") and request.method == "POST":
                length = request.headers.get("content-length", "0")
                if not length.isdigit() or int(length) > 2 * 1024 * 1024:
                    return JSONResponse({"detail": "Cet ensemble est trop volumineux."}, status_code=413)
                if len(await request.body()) > 2 * 1024 * 1024:
                    return JSONResponse({"detail": "Cet ensemble est trop volumineux."}, status_code=413)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        return await call_next(request)

    def current_user(request, allow_password_change=False):
        user = app.state.accounts.resolve(request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, "Connecte-toi pour retrouver ton espace.")
        if user["must_change_password"] and not allow_password_change:
            raise HTTPException(403, "Change ton mot de passe pour commencer.")
        return user

    @app.exception_handler(DeckError)
    async def deck_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    def library_for(request):
        if not auth_enabled or app.state.decks is None:
            raise HTTPException(403, "La bibliothèque MongoDB n’est pas activée.")
        return current_user(request), app.state.decks

    def local_set(request):
        if auth_enabled:
            current_user(request)
        source = raw_cards if raw_cards is not None else json.loads((DATA_DIR / "flashcards.json").read_text(encoding="utf-8"))
        return dict(id=DEFAULT_SET_ID, title="Éthique de l’ingénieur", description="L’ensemble d’origine de Mémo.",
                    editable=False, shared=False, revision="local", latest_version=1, version=1,
                    versions=[dict(version=1, card_count=len(source))],
                    cards=[dict(term=term, definition=definition) for term, definition in source])

    def study_for(request, set_id=None, version=None):
        if not auth_enabled:
            return app.state.study, app.state.lock
        user = current_user(request)
        cards = raw_cards
        path = app.state.accounts.progress_path(user["id"])
        key = user["id"]
        if app.state.decks is not None:
            deck = app.state.decks.get(user, set_id or DEFAULT_SET_ID, version if set_id else 1)
            cards = validate_cards(deck["cards"])
            key = (user["id"], deck["id"], deck["version"])
            if not (deck["id"] == DEFAULT_SET_ID and deck["version"] == 1):
                path = path.parent / "sets" / deck["id"] / f'v{deck["version"]}.json'
        elif set_id is not None:
            raise HTTPException(403, "La bibliothèque MongoDB n’est pas activée.")
        with app.state.lock:
            if key not in app.state.studies:
                try:
                    study = WebStudy(path, None, cards, config)
                except (ValueError, OSError) as error:
                    raise HTTPException(503, "Ta progression ne peut pas être chargée. Contacte l’administrateur.") from error
                app.state.studies[key] = study, RLock()
            return app.state.studies[key]

    @app.get("/api/sets")
    def sets(request: Request):
        if app.state.decks is None or not auth_enabled:
            deck = local_set(request)
            return {"enabled": False, "default_set_id": DEFAULT_SET_ID,
                    "sets": [{key: value for key, value in deck.items() if key not in ("cards", "version")}]}
        user, repository = library_for(request)
        return {"enabled": True, "default_set_id": DEFAULT_SET_ID, "sets": repository.list(user)}

    @app.get("/api/sets/{identifier}")
    def get_set(identifier: str, request: Request, version: int | None = Query(default=None, ge=1)):
        if app.state.decks is None or not auth_enabled:
            deck = local_set(request)
            if identifier != DEFAULT_SET_ID or version not in (None, 1):
                raise HTTPException(404, "Ensemble introuvable.")
            return deck
        user, repository = library_for(request)
        return repository.get(user, identifier, version)

    @app.post("/api/sets", status_code=201)
    def create_set(body: SetInput, request: Request):
        user, repository = library_for(request)
        with app.state.lock:
            return repository.save(user, body.title, body.description, [card.model_dump() for card in body.cards])

    @app.post("/api/sets/{identifier}")
    def edit_set(identifier: str, body: SetInput, request: Request):
        user, repository = library_for(request)
        return repository.save(user, body.title, body.description, [card.model_dump() for card in body.cards], identifier, body.revision)

    def set_cookie(response, token):
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=require_https, samesite="strict", path=cookie_path)

    @app.get("/api/auth/me")
    def me(request: Request):
        return {"enabled": auth_enabled, "user": Accounts.public(current_user(request, True)) if auth_enabled else None}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        if not auth_enabled:
            raise HTTPException(403, "Les comptes sont désactivés dans cet espace local.")
        try:
            result = app.state.accounts.login(body.username, body.password, request.client.host if request.client else "unknown")
        except PermissionError as error:
            raise HTTPException(429, str(error)) from error
        if result is None:
            raise HTTPException(401, "Identifiant ou mot de passe incorrect.")
        user, token = result
        app.state.accounts.logout(request.cookies.get(COOKIE))
        set_cookie(response, token)
        return {"enabled": True, "user": Accounts.public(user)}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        if auth_enabled:
            app.state.accounts.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path=cookie_path, secure=require_https, httponly=True, samesite="strict")
        return {"status": "ok"}

    @app.post("/api/auth/password")
    def password(body: PasswordChange, request: Request, response: Response):
        if not auth_enabled:
            raise HTTPException(403, "Les comptes sont désactivés dans cet espace local.")
        user = current_user(request, True)
        if not PASSWORDS.verify(body.current_password, user["password_hash"]):
            raise HTTPException(403, "Le mot de passe actuel est incorrect.")
        if body.current_password == body.new_password:
            raise HTTPException(400, "Choisis un nouveau mot de passe différent.")
        app.state.accounts.set_password(user["id"], body.new_password)
        # Password changes invalidate all sessions, then issue one fresh session.
        user, token = app.state.accounts.issue_session(app.state.accounts.user(user["username"]))
        set_cookie(response, token)
        return {"enabled": True, "user": Accounts.public(user)}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/state")
    def state(request: Request, response: Response, set_id: str | None = None, version: int | None = Query(default=None, ge=1)):
        response.headers["Cache-Control"] = "no-store"
        study, lock = study_for(request, set_id, version)
        with lock:
            return study.snapshot()

    @app.post("/api/actions")
    def act(action: Action, request: Request, response: Response, set_id: str | None = None, version: int | None = Query(default=None, ge=1)):
        response.headers["Cache-Control"] = "no-store"
        study, lock = study_for(request, set_id, version)
        with lock:
            if action.revision != study.revision:
                raise HTTPException(409, "La session a changé dans un autre onglet. La vue a été actualisée ; recommence ton action.")
            try:
                return study.apply(action)
            except InvalidAction as error:
                raise HTTPException(400, str(error)) from error
            except OSError as error:
                raise HTTPException(503, "La sauvegarde a échoué. Ton action n’a pas été enregistrée ; réessaie.") from error

    # A production build is served on the same origin as the API.
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
