import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import mongomock
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from backend.auth import Accounts
from backend.decks import MongoDecks
from backend.main import create_app
from backend.reference_documents import MAX_UPLOAD_BYTES, ReferenceDocuments, convert_office, presentation_annotations, presentation_notes
from backend.tests.document_fixtures import course_pdf, course_pptx

PASSWORD = "reference-test-passphrase-123"
HEADERS = {"Origin": "https://memo.test", "X-Memo-Request": "1"}
CARDS = [{"term": "Question", "definition": "Réponse"}]


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.accounts = Accounts(self.directory)
        self.owner = self.accounts.create("owner", "Owner", PASSWORD, must_change=False)
        self.other = self.accounts.create("other", "Other", PASSWORD, must_change=False)
        self.repository = MongoDecks(mongomock.MongoClient().memo.sets)
        self.client = TestClient(create_app(auth_enabled=True, require_https=True,
            data_dir=self.directory, deck_repository=self.repository), base_url="https://memo.test").__enter__()
        self.login()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, user="owner"):
        self.client.post("/api/auth/login", json={"username": user, "password": PASSWORD}, headers=HEADERS)

    def upload(self, path, name=None, headers=None):
        return self.client.post("/api/reference-documents", content=path.read_bytes(), headers={
            **HEADERS, "Content-Type": "application/octet-stream", "X-Memo-Filename": name or path.name, **(headers or {})})

    def save(self, identifiers, deck=None, **values):
        return self.client.post("/api/sets" + ("/" + deck["id"] if deck else ""), json={
            "title": "Cours", "cards": CARDS, "document_ids": identifiers,
            **({"revision": deck["revision"]} if deck else {}), **values}, headers=HEADERS)

    def test_pdf_upload_link_persistence_remove_and_no_card_version_change(self):
        pdf = course_pdf(self.directory / "Chapitre.pdf")
        result = self.upload(pdf)
        self.assertEqual(result.status_code, 201, result.text)
        document = result.json()
        self.assertEqual(document["page_count"], 3)
        self.assertNotIn("owner_id", document)
        saved = self.save([document["id"]])
        self.assertEqual(saved.status_code, 201, saved.text)
        deck = saved.json()
        self.assertEqual(deck["documents"], [document])
        content = self.client.get(f'/api/reference-documents/{document["id"]}/pdf')
        self.assertEqual(content.headers["content-type"], "application/pdf")
        self.assertEqual(len(PdfReader(io.BytesIO(content.content)).pages), 3)
        # A fresh service instance sees the same PDF and notes on the data volume.
        self.assertEqual(ReferenceDocuments(self.directory).metadata(document["id"])["page_count"], 3)
        changed = self.save([], deck).json()
        self.assertEqual(changed["version"], 1)
        self.assertEqual(changed["documents"], [])
        stale = self.save([document["id"]], deck)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.client.get(f'/api/sets/{deck["id"]}').json()["documents"], [])

    def test_privacy_drafts_shared_reads_and_cross_user_attachment(self):
        document = self.upload(course_pdf(self.directory / "Cours.pdf")).json()
        identifier = document["id"]
        deck = self.save([identifier]).json()
        self.login("other")
        for suffix in ("", "/pdf", "/pdf?set_id=" + deck["id"]):
            self.assertEqual(self.client.get(f'/api/reference-documents/{identifier}{suffix}').status_code, 404)
        self.assertEqual(self.save([identifier]).status_code, 404)
        self.repository.collection.update_one({"_id": deck["id"]}, {"$set": {"shared": True}})
        self.assertEqual(self.client.get(f'/api/reference-documents/{identifier}/pdf?set_id={deck["id"]}').status_code, 200)
        self.assertEqual(self.client.get(f'/api/sets/{deck["id"]}').json()["documents"], [document])
        self.client.cookies.clear()
        self.assertEqual(self.client.get(f'/api/reference-documents/{identifier}/pdf').status_code, 401)

    def test_upload_limits_type_password_and_origin_guards(self):
        pdf = course_pdf(self.directory / "Cours.pdf")
        self.assertEqual(self.upload(pdf, "bad.exe").status_code, 400)
        self.assertEqual(self.upload(pdf, headers={"Origin": "https://other.test"}).status_code, 403)
        self.assertEqual(self.upload(pdf, headers={"X-Memo-Request": "0"}).status_code, 403)
        self.assertEqual(self.upload(pdf, headers={"Content-Type": "application/json"}).status_code, 403)
        self.assertEqual(self.upload(pdf, headers={"Content-Length": str(MAX_UPLOAD_BYTES + 1)}).status_code, 413)
        self.assertEqual(self.client.post("/api/reference-documents", content=(b"x" for _ in range(2)), headers={
            **HEADERS, "Content-Type": "application/octet-stream", "X-Memo-Filename": "bad.pdf"}).status_code, 400)
        with patch("backend.main.MAX_UPLOAD_BYTES", 1):
            streamed = self.client.post("/api/reference-documents", content=(b"x" for _ in range(2)), headers={
                **HEADERS, "Content-Type": "application/octet-stream", "X-Memo-Filename": "large.pdf"})
            self.assertEqual(streamed.status_code, 413)
        invalid = self.directory / "invalid.pdf"
        invalid.write_bytes(b"%PDF-1.4\nbroken")
        self.assertEqual(self.upload(invalid).status_code, 400)
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.encrypt("secret")
        writer.write(self.directory / "locked.pdf")
        self.assertEqual(self.upload(self.directory / "locked.pdf").status_code, 400)
        self.assertEqual(self.save(["../unsafe"]).status_code, 404)
        document = self.upload(pdf).json()
        self.assertEqual(self.save([document["id"], document["id"]]).status_code, 400)
        self.assertEqual(self.save([document["id"]] * 21).status_code, 422)

    def test_notes_follow_relationships_and_empty_notes_remain_aligned(self):
        path = course_pptx(self.directory / "Cours.pptx")
        self.assertEqual(presentation_notes(path), ["", "Notes de la première slide.\nDeuxième paragraphe.", "Notes de la slide masquée."])

    def test_valid_package_relationships_and_comments_follow_slide_order(self):
        path = course_pptx(self.directory / "Commentaires.pptx", annotations=True)
        annotations = presentation_annotations(path)
        self.assertEqual(annotations["notes"], presentation_notes(course_pptx(self.directory / "Notes.pptx")))
        self.assertEqual(annotations["comments"], [[], [
            {"author": "Professeur", "text": "Préciser cet exemple.", "replies": []}], [
            {"author": "Enseignante", "text": "Commentaire sur la slide masquée.\nÀ revoir.",
                "replies": [{"author": "Étudiant", "text": "Bien compris."}]}]])

    def test_internal_relationships_cannot_escape_the_package(self):
        for target in ("../../outside.xml", "%2E%2E/%2E%2E/outside.xml", "file:///outside.xml", "..\\outside.xml"):
            with self.subTest(target=target):
                path = course_pptx(self.directory / "Unsafe.pptx", annotations=True)
                with zipfile.ZipFile(path) as archive:
                    parts = {name: archive.read(name) for name in archive.namelist()}
                name = "ppt/_rels/presentation.xml.rels"
                parts[name] = parts[name].replace(b"../docProps/thumbnail.jpeg", target.encode())
                with zipfile.ZipFile(path, "w") as archive:
                    for name, content in parts.items():
                        archive.writestr(name, content)
                self.assertEqual(self.upload(path).status_code, 400)

    @unittest.skipUnless(shutil.which("libreoffice") or shutil.which("soffice"), "LibreOffice is required for conversion integration")
    def test_real_powerpoint_upload_displays_slides_notes_and_comments(self):
        path = course_pptx(self.directory / "Commentaires.pptx", annotations=True)
        response = self.upload(path)
        self.assertEqual(response.status_code, 201, response.text)
        document = response.json()
        metadata = self.client.get(f'/api/reference-documents/{document["id"]}').json()
        self.assertEqual(metadata["comments"], presentation_annotations(path)["comments"])
        self.assertEqual(metadata["notes"], presentation_notes(path))
        persisted = ReferenceDocuments(self.directory).metadata(document["id"])
        self.assertEqual(persisted["comments"], metadata["comments"])
        pages = PdfReader(io.BytesIO(self.client.get(f'/api/reference-documents/{document["id"]}/pdf').content)).pages
        self.assertEqual(len(pages), 3)
        self.assertIn("Conclusion", pages[0].extract_text())
        self.assertIn("Introduction", pages[1].extract_text())
        self.assertIn("masquée", pages[2].extract_text())

    def test_malformed_and_unsafe_xml_are_rejected_and_converter_absence_is_clear(self):
        path = self.directory / "bad.pptx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("ppt/presentation.xml", '<!DOCTYPE root [<!ENTITY x "unsafe">]><root>&x;</root>')
        self.assertEqual(self.upload(path).status_code, 400)
        with patch("backend.reference_documents.shutil.which", return_value=None), patch.dict("os.environ", {"MEMO_LIBREOFFICE_BIN": ""}):
            response = self.upload(course_pptx(self.directory / "Cours.pptx"))
        self.assertEqual(response.status_code, 503)
        self.assertIn("LibreOffice", response.json()["detail"])

    @unittest.skipUnless(shutil.which("libreoffice") or shutil.which("soffice"), "LibreOffice is required for conversion integration")
    def test_real_pptx_and_legacy_ppt_conversion_keep_notes_and_hidden_slides(self):
        source = course_pptx(self.directory / "Cours.pptx")
        for path in (source, convert_office(source, self.directory, "ppt:MS PowerPoint 97")):
            with self.subTest(format=path.suffix):
                response = self.upload(path)
                self.assertEqual(response.status_code, 201, response.text)
                document = response.json()
                self.assertEqual(document["page_count"], 3)
                metadata = self.client.get(f'/api/reference-documents/{document["id"]}').json()
                self.assertEqual(metadata["notes"], ["", "Notes de la première slide.\nDeuxième paragraphe.", "Notes de la slide masquée."])
                content = self.client.get(f'/api/reference-documents/{document["id"]}/pdf').content
                pages = PdfReader(io.BytesIO(content)).pages
                self.assertIn("Conclusion", pages[0].extract_text())
                self.assertIn("Introduction", pages[1].extract_text())
                self.assertIn("masquée", pages[2].extract_text())

    def test_existing_api_clients_preserve_documents_when_field_is_omitted(self):
        document = self.upload(course_pdf(self.directory / "Cours.pdf")).json()
        deck = self.save([document["id"]]).json()
        result = self.client.post("/api/sets/" + deck["id"], json={"title": "Nouveau titre", "cards": CARDS,
            "revision": deck["revision"]}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["documents"], [document])
