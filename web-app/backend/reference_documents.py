"""Private reference PDFs and per-slide notes, stored on the persistent data volume."""
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .decks import DeckError

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_DOCUMENTS = 20
MAX_PAGES = 500
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
COMMENTS = "{http://schemas.microsoft.com/office/powerpoint/2018/8/main}"
CONVERSIONS = threading.BoundedSemaphore(2)


def document_id(value):
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise DeckError(404, "Document introuvable.")
    return value


def presentation_notes(path):
    return presentation_annotations(path)["notes"]


def presentation_annotations(path):
    """Follow presentation/slide relationships, never ZIP filename order.

    Body and custom text placeholders are notes; slide image, date, footer and
    slide-number placeholders are deliberately excluded.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 10000 or sum(i.file_size for i in archive.infolist()) > 150 * 1024 * 1024:
                raise DeckError(400, "Ce PowerPoint décompressé est trop volumineux.")

            names = set(archive.namelist())

            def xml(part):
                if archive.getinfo(part).file_size > 8 * 1024 * 1024:
                    raise DeckError(400, "Ce PowerPoint contient une section trop volumineuse.")
                return ET.fromstring(archive.read(part))

            def relationships(part):
                folder, name = posixpath.split(part)
                rels = posixpath.join(folder, "_rels", name + ".rels")
                if rels not in names:
                    return {}
                result = {}
                for rel in xml(rels):
                    if rel.get("TargetMode") == "External":
                        continue
                    target = unquote(rel.get("Target", ""))
                    resolved = posixpath.normpath(posixpath.join(folder, target) if not target.startswith("/") else target.lstrip("/"))
                    # Package parts can live outside ppt/ (e.g. docProps thumbnails
                    # and customXml). Only reject paths escaping the ZIP package.
                    if not target or "\\" in target or ":" in target or resolved in (".", "..") or resolved.startswith("../"):
                        raise DeckError(400, "Les liens internes de ce PowerPoint sont invalides.")
                    result[rel.get("Id")] = (rel.get("Type", ""), resolved)
                return result

            order = xml("ppt/presentation.xml").find(f"{P}sldIdLst")
            if order is None or not 1 <= len(order) <= MAX_PAGES:
                raise DeckError(400, f"Le PowerPoint doit contenir entre 1 et {MAX_PAGES} slides.")
            slides = relationships("ppt/presentation.xml")
            authors = {}
            for kind, target in slides.values():
                if kind.endswith(("/commentAuthors", "/authors")):
                    for author in xml(target):
                        if author.tag in (f"{P}cmAuthor", f"{COMMENTS}author"):
                            authors[(author.tag.rsplit("}", 1)[0] + "}", author.get("id"))] = author.get("name", "")

            def comment_text(element, namespace):
                if namespace == P:
                    text = element.findtext(f"{P}text", "").strip()
                else:
                    text = "\n".join("".join("\n" if item.tag == f"{A}br" else item.text or ""
                        for item in paragraph.iter() if item.tag in (f"{A}t", f"{A}br"))
                        for paragraph in element.findall(f"{COMMENTS}txBody/{A}p")).strip()
                return {"author": authors.get((namespace, element.get("authorId")), ""), "text": text}

            notes = []
            comments = []
            for entry in order:
                kind, slide = slides[entry.get(f"{R}id")]
                if not kind.endswith("/slide"):
                    raise DeckError(400, "Les liens internes de ce PowerPoint sont invalides.")
                slide_links = relationships(slide)
                note_part = next((target for kind, target in slide_links.values() if kind.endswith("/notesSlide")), None)
                paragraphs = []
                if note_part:
                    for shape in xml(note_part).iter(f"{P}sp"):
                        placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                        if placeholder is not None and placeholder.get("type") in ("sldImg", "sldNum", "dt", "hdr", "ftr"):
                            continue
                        for paragraph in shape.findall(f"{P}txBody/{A}p"):
                            # Legacy PPT normalization may turn footer placeholders
                            # into ordinary shapes containing automatic fields.
                            parts = []
                            for run in paragraph:
                                if run.tag == f"{A}fld" and run.get("type", "").lower().startswith(("slidenum", "datetime", "footer", "header")):
                                    continue
                                parts.extend("\n" if item.tag == f"{A}br" else item.text or "" for item in run.iter() if item.tag in (f"{A}t", f"{A}br"))
                            if parts:
                                paragraphs.append("".join(parts))
                text = "\n".join(paragraphs).strip()
                if len(text) > 100000:
                    raise DeckError(400, "Les notes d’une slide sont trop longues.")
                notes.append(text)
                slide_comments = []
                for kind, target in slide_links.values():
                    if not kind.endswith("/comments"):
                        continue
                    for element in xml(target):
                        namespace = P if element.tag == f"{P}cm" else COMMENTS if element.tag == f"{COMMENTS}cm" else None
                        if namespace is None:
                            continue
                        comment = comment_text(element, namespace)
                        comment["replies"] = [comment_text(reply, COMMENTS) for reply in element.findall(f"{COMMENTS}replyLst/{COMMENTS}reply")]
                        slide_comments.append(comment)
                if len(slide_comments) + sum(len(comment["replies"]) for comment in slide_comments) > 1000:
                    raise DeckError(400, "Cette slide contient trop de commentaires.")
                comments.append(slide_comments)
            if sum(map(len, notes)) + len(json.dumps(comments, ensure_ascii=False)) > 2 * 1024 * 1024:
                raise DeckError(400, "Les notes et commentaires de ce PowerPoint sont trop volumineux.")
            return {"notes": notes, "comments": comments}
    except DeckError:
        raise
    except (KeyError, ValueError, ET.ParseError, DefusedXmlException, zipfile.BadZipFile, RuntimeError, OSError):
        raise DeckError(400, "Ce PowerPoint est endommagé ou son format n’est pas pris en charge.") from None


def convert_office(source, output, target):
    executable = os.environ.get("MEMO_LIBREOFFICE_BIN") or shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise DeckError(503, "La conversion PowerPoint nécessite LibreOffice sur le serveur. Tu peux ajouter un PDF en attendant.")
    profile = output / ("profile-" + uuid.uuid4().hex)
    profile.mkdir()
    # No macros, automatic external-link updates or shared desktop profile.
    (profile / "user").mkdir()
    (profile / "user" / "registrymodifications.xcu").write_text('''<?xml version="1.0"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Update"><prop oor:name="LinkUpdateMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>''', encoding="utf-8")
    try:
        process = subprocess.Popen([executable, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
            "--nodefault", "--norestore", "--convert-to", target, "--outdir", str(output), str(source)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            code = process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise DeckError(422, "La conversion a pris trop de temps. Réessaie avec un fichier plus petit ou un PDF.") from None
        converted = output / f"{source.stem}.{target.split(':')[0]}"
        if code != 0 or not converted.is_file():
            raise DeckError(422, "La conversion de ce PowerPoint a échoué. Vérifie le fichier ou ajoute une version PDF.")
        return converted
    except OSError:
        raise DeckError(503, "Le service de conversion PowerPoint n’est pas disponible.") from None


class ReferenceDocuments:
    def __init__(self, directory):
        self.directory = Path(directory) / "reference-documents"

    def _folder(self, identifier):
        return self.directory / document_id(identifier)

    @staticmethod
    def public(metadata):
        return {key: metadata[key] for key in ("id", "name", "kind", "page_count")}

    def metadata(self, identifier):
        try:
            return json.loads((self._folder(identifier) / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise DeckError(404, "Document introuvable. Ajoute-le à nouveau si nécessaire.") from None

    def attachments(self, user, identifiers):
        if len(identifiers) > MAX_DOCUMENTS or len(set(identifiers)) != len(identifiers):
            raise DeckError(400, f"Choisis au maximum {MAX_DOCUMENTS} documents différents.")
        for identifier in identifiers:
            if self.metadata(identifier)["owner_id"] != user["id"]:
                raise DeckError(404, "Document introuvable.")

    def authorize(self, user, identifier, repository, set_id=None):
        metadata = self.metadata(identifier)
        if metadata["owner_id"] == user["id"]:
            return metadata
        if set_id and identifier in repository.get(user, set_id).get("document_ids", []):
            return metadata
        raise DeckError(404, "Document introuvable.")

    def details(self, deck):
        return {**deck, "documents": [self.public(self.metadata(identifier)) for identifier in deck.get("document_ids", [])]}

    def create(self, user, source, name):
        name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
        suffix = Path(name).suffix.lower()
        if suffix not in (".pdf", ".ppt", ".pptx") or not 1 <= len(name) <= 255 or any(ord(c) < 32 for c in name):
            raise DeckError(400, "Choisis un fichier PDF, PPT ou PPTX avec un nom valide.")
        if not 0 < source.stat().st_size <= MAX_UPLOAD_BYTES:
            raise DeckError(413, "Le document doit peser au maximum 30 Mio et ne pas être vide.")
        self.directory.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="conversion-", dir=self.directory) as temporary:
            work = Path(temporary)
            input_file = work / ("course" + suffix)
            shutil.copyfile(source, input_file)
            notes = []
            comments = []
            pdf = input_file
            if suffix == ".pdf":
                if not input_file.read_bytes()[:1024].lstrip().startswith(b"%PDF-"):
                    raise DeckError(400, "Ce fichier n’est pas un PDF valide.")
            else:
                if not CONVERSIONS.acquire(blocking=False):
                    raise DeckError(503, "Deux documents sont déjà en conversion. Réessaie dans un instant.")
                try:
                    if suffix == ".ppt":
                        if input_file.read_bytes()[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                            raise DeckError(400, "Ce fichier n’est pas un PowerPoint PPT valide.")
                        input_file = convert_office(input_file, work, "pptx:Impress MS PowerPoint 2007 XML")
                    annotations = presentation_annotations(input_file)
                    notes, comments = annotations["notes"], annotations["comments"]
                    # Include hidden slides to maintain the exact notes/page mapping.
                    options = json.dumps({"ExportHiddenSlides": {"type": "boolean", "value": "true"},
                        "ExportNotesPages": {"type": "boolean", "value": "false"}})
                    pdf = convert_office(input_file, work, "pdf:impress_pdf_Export:" + options)
                finally:
                    CONVERSIONS.release()
            try:
                reader = PdfReader(pdf)
                if reader.is_encrypted:
                    raise DeckError(400, "Les PDF protégés par mot de passe ne sont pas pris en charge.")
                page_count = len(reader.pages)
            except (PyPdfError, ValueError, OSError):
                raise DeckError(400, "Le PDF est endommagé ou illisible.") from None
            if not 1 <= page_count <= MAX_PAGES:
                raise DeckError(400, f"Le document doit contenir entre 1 et {MAX_PAGES} pages.")
            if notes and page_count != len(notes):
                raise DeckError(422, "La conversion n’a pas conservé toutes les slides. Ajoute une version PowerPoint standard.")
            metadata = dict(id=identifier, owner_id=user["id"], name=name, kind=suffix[1:], page_count=page_count, notes=notes, comments=comments)
            ready = work / "ready"
            ready.mkdir()
            shutil.copyfile(pdf, ready / "document.pdf")
            (ready / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            ready.rename(self._folder(identifier))
            return self.public(metadata)

    def pdf_path(self, identifier):
        path = self._folder(identifier) / "document.pdf"
        if not path.is_file():
            raise DeckError(404, "Le PDF de référence est introuvable.")
        return path
