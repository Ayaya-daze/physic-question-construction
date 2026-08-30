from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
import httpx
from PIL import Image

from app.api import file_questions as file_api
from app.config import settings
from app.services import file_question_importer as importer
from app.services import file_question_store as store
from app.services.file_question_candidates import (
    approve_candidate,
    create_candidate,
    list_candidates,
)
from app.services.file_knowledge_points import (
    list_knowledge_points,
    merge_knowledge_points,
    rename_knowledge_point,
)
from app.services.file_question_importer import _parse_llm_json, import_source_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_MATERIALIZER = (
    PROJECT_ROOT
    / "skills"
    / "physics-question-importer"
    / "scripts"
    / "materialize_questions.py"
)


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (24, 18), color=(240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


class IsolatedFileStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.questions_dir = self.root / "questions"
        self.upload_dir = self.root / "uploads"
        self.exports_dir = self.root / "exports"
        self.index_dir = self.questions_dir / ".index"
        self.patches = [
            patch.object(settings, "QUESTIONS_DIR", str(self.questions_dir)),
            patch.object(settings, "UPLOAD_DIR", str(self.upload_dir)),
            patch.object(settings, "EXPORTS_DIR", str(self.exports_dir)),
            patch.object(settings, "LATEX_ENGINE", "missing-xelatex-for-test"),
            patch.object(settings, "EMBEDDING_ENABLED", False),
            patch.object(store, "QUESTIONS_DIR", self.questions_dir),
            patch.object(store, "INDEX_DIR", self.index_dir),
            patch.object(store, "INDEX_PATH", self.index_dir / "vector-index.json"),
            patch.object(store, "LEXICAL_INDEX_PATH", self.index_dir / "lexical.sqlite"),
            patch.object(store, "VECTOR_DATA_PATH", self.index_dir / "vectors.f32"),
            patch.object(store, "VECTOR_MAP_PATH", self.index_dir / "vector-map.json"),
            patch.object(store, "INDEX_MANIFEST_PATH", self.index_dir / "index-manifest.json"),
            patch.object(file_api, "INDEX_PATH", self.index_dir / "vector-index.json"),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temporary.cleanup()

    def test_atomic_write_and_idempotency(self) -> None:
        first = store.write_question(
            question_id="qf_atomic",
            question_body="# Test\n\nValue is $v$.",
            answer_body="$v=1$.",
            metadata={"title": "Test"},
            assets=[("diagram.png", png_bytes())],
        )
        self.assertEqual(first.question_id, "qf_atomic")
        original_fingerprint = store.record_fingerprint("qf_atomic")

        same = store.write_question(
            question_id="qf_atomic",
            question_body="# Test\n\nValue is $v$.",
            answer_body="$v=1$.",
            metadata={"title": "Test"},
            assets=[("diagram.png", png_bytes())],
            idempotent=True,
        )
        self.assertEqual(same.question_id, "qf_atomic")
        self.assertEqual(original_fingerprint, store.record_fingerprint("qf_atomic"))

        with self.assertRaises(ValueError):
            store.write_question(
                question_id="qf_atomic",
                question_body="changed",
                metadata={"title": "Changed"},
                assets=[("broken.png", b"not an image")],
                overwrite=True,
            )
        self.assertEqual(original_fingerprint, store.record_fingerprint("qf_atomic"))
        self.assertFalse(any((self.questions_dir / ".staging").iterdir()))

    def test_interrupted_directory_swap_is_recovered(self) -> None:
        store.write_question(
            question_id="qf_recover",
            question_body="Original question.",
        )
        staging = self.questions_dir / ".staging"
        question_dir = self.questions_dir / "qf_recover"
        backup = staging / ("qf_recover." + "a" * 32 + ".backup")
        temporary = staging / ("qf_recover." + "b" * 32 + ".tmp")
        question_dir.replace(backup)
        temporary.mkdir()
        (temporary / "question.md").write_text("Incomplete", encoding="utf-8")

        result = store.recover_interrupted_writes()

        self.assertEqual(result["restored"], 1)
        self.assertEqual(store.read_question("qf_recover").question_body, "Original question.")
        self.assertFalse(backup.exists())
        self.assertFalse(temporary.exists())

    def test_question_and_asset_symlinks_are_rejected(self) -> None:
        store.ensure_store()
        # Creating symlinks requires administrator privileges or Developer Mode
        # on Windows; skip the safety check when the platform forbids them
        # (the test's logic needs a real symlink to exercise).
        try:
            probe = self.questions_dir / "symlink_probe"
            probe.symlink_to(self.root, target_is_directory=True)
            probe.unlink()
        except OSError:
            self.skipTest("Symbolic links are not permitted on this system")
        external = self.root / "external"
        external.mkdir()
        (external / "question.md").write_text("External question.", encoding="utf-8")
        (self.questions_dir / "qf_link").symlink_to(external, target_is_directory=True)
        with self.assertRaises(FileNotFoundError):
            store.read_question("qf_link")

        store.write_question(
            question_id="qf_asset_link",
            question_body="Question.",
        )
        external_asset = self.root / "outside.png"
        external_asset.write_bytes(png_bytes())
        assets = self.questions_dir / "qf_asset_link" / "assets"
        assets.mkdir()
        (assets / "outside.png").symlink_to(external_asset)
        with self.assertRaises(FileNotFoundError):
            store.asset_path("qf_asset_link", "outside.png")

    def test_candidate_requires_explicit_warning_acknowledgement(self) -> None:
        candidate = create_candidate(
            question_body="A block has mass $m$.",
            answer_body="Use $F=ma$.",
            question_format="markdown",
            answer_format="markdown",
            metadata={"title": "Dynamics", "knowledge_points": ["Newton law"]},
            assets=[],
            proposed_question_id="qf_candidate",
            source_filename="paper.pdf",
            source_type="pdf",
            source_document_hash="a" * 64,
            warnings=["source boundary requires review"],
        )
        with self.assertRaises(ValueError):
            approve_candidate(candidate["candidate_id"])
        self.assertEqual(len(list_candidates(state="needs_review")), 1)

        committed, question = approve_candidate(
            candidate["candidate_id"],
            acknowledge_warnings=True,
        )
        self.assertEqual(committed["state"], "committed")
        self.assertEqual(question.question_id, "qf_candidate")
        self.assertFalse(question.metadata["human_review_needed"])
        self.assertEqual(list_candidates(state="needs_review"), [])

    def test_local_hybrid_index_files_and_search(self) -> None:
        store.write_question(
            question_id="qf_newton",
            question_body="牛顿第二定律：合力等于质量与加速度的乘积。",
            metadata={"knowledge_points": ["牛顿第二定律"]},
        )
        store.write_question(
            question_id="qf_optics",
            question_body="薄透镜成像与焦距。",
            metadata={"knowledge_points": ["几何光学"]},
        )
        payload = store.rebuild_index()
        self.assertEqual(len(payload["items"]), 2)
        for path in (
            store.INDEX_PATH,
            store.LEXICAL_INDEX_PATH,
            store.VECTOR_DATA_PATH,
            store.VECTOR_MAP_PATH,
            store.INDEX_MANIFEST_PATH,
        ):
            self.assertTrue(path.is_file(), path)
        results = store.search_questions("牛顿第二定律", limit=5)
        self.assertTrue(results)
        self.assertEqual(results[0].question_id, "qf_newton")

    def test_embedding_api_failure_falls_back_to_local_index(self) -> None:
        store.write_question(
            question_id="qf_fallback",
            question_body="A searchable fallback question.",
        )
        with (
            patch.object(settings, "EMBEDDING_ENABLED", True),
            patch.object(settings, "EMBEDDING_API_KEY", "test-key"),
            patch.object(settings, "EMBEDDING_MODEL", "test-model"),
            patch.object(
                store,
                "embed_texts",
                side_effect=httpx.ConnectError("embedding service unavailable"),
            ),
        ):
            payload = store.rebuild_index()

        self.assertEqual(payload["model"], store.LOCAL_VECTOR_MODEL)
        manifest = json.loads(store.INDEX_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["embedding_provider"], "local-fallback")
        self.assertIn("embedding service unavailable", manifest["embedding_error"])

    def test_dynamic_knowledge_points_rename_merge_and_filter(self) -> None:
        store.write_question(
            question_id="qf_kp_1",
            question_body="Question one.",
            metadata={"knowledge_points": ["Dynamics"]},
        )
        store.write_question(
            question_id="qf_kp_2",
            question_body="Question two.",
            metadata={"knowledge_points": ["Newton law"]},
        )
        store.rebuild_index()
        items = list_knowledge_points()
        self.assertEqual(len(items), 2)
        source = next(item for item in items if item["name"] == "Dynamics")
        target = next(item for item in items if item["name"] == "Newton law")
        renamed = rename_knowledge_point(source["knowledge_point_id"], "Mechanics")
        self.assertIn("Dynamics", renamed["aliases"])
        merged = merge_knowledge_points(
            source["knowledge_point_id"],
            target["knowledge_point_id"],
        )
        self.assertEqual(len(merged["items"]), 1)
        self.assertEqual(merged["items"][0]["count"], 2)
        response = asyncio.run(
            file_api.list_file_questions(
                q=None,
                knowledge_point_id=target["knowledge_point_id"],
                skip=0,
                limit=20,
            )
        )
        self.assertEqual(response.total, 2)

    def test_structured_import_review_gate(self) -> None:
        source = self.root / "import.json"
        source.write_text(
            json.dumps(
                [
                    {
                        "question_body": "Reviewed source question.",
                        "answer_body": "",
                        "metadata": {
                            "title": "Review",
                            "knowledge_points": ["Generated topic"],
                            "human_review_needed": True,
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = asyncio.run(
            import_source_file(
                source_path=source,
                original_filename="import.json",
                rebuild_after=False,
            )
        )
        self.assertEqual(result.questions, [])
        self.assertEqual(len(result.candidates), 1)
        self.assertFalse(any(self.questions_dir.glob("qf_*")))

    def test_llm_json_parser_accepts_nested_arrays_in_fenced_json(self) -> None:
        content = r"""```json
[
  {
    "question_body": "A diagram on line $OO\'$ is marked [see source page].
Find $v$.",
    "answer_body": "",
    "metadata": {
      "knowledge_points": ["kinematics", "energy"],
      "source_pages": [1],
      "human_review_needed": true
    }
  }
]
```"""

        items = _parse_llm_json(content)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metadata"]["source_pages"], [1])
        self.assertEqual(items[0]["metadata"]["knowledge_points"], ["kinematics", "energy"])

    def test_vision_import_batches_multi_page_documents(self) -> None:
        class FakeVisionProvider:
            supports_vision = True

            def __init__(self) -> None:
                self.batch_sizes: list[int] = []

            async def complete_with_images(self, *, image_data: list[str], **kwargs):
                self.batch_sizes.append(len(image_data))
                index = len(self.batch_sizes)
                return type(
                    "Response",
                    (),
                    {
                        "content": json.dumps(
                            [
                                {
                                    "question_body": f"Question from page batch {index}.",
                                    "answer_body": "",
                                    "metadata": {"knowledge_points": []},
                                }
                            ]
                        )
                    },
                )()

        provider = FakeVisionProvider()
        assets = [
            importer.SourceAsset(
                filename=f"page_{page:03d}.png",
                payload=png_bytes(),
                page_number=page,
            )
            for page in range(1, 6)
        ]
        config = {
            "enabled": True,
            "configured": True,
            "supports_vision": True,
        }

        with (
            patch.object(importer, "llm_import_config", return_value=config),
            patch.object(importer, "get_llm_provider", return_value=provider),
        ):
            items = asyncio.run(
                importer._vision_split_into_file_questions(
                    page_assets=assets,
                    ocr_page_texts=[],
                    original_filename="paper.pdf",
                )
            )

        self.assertEqual(provider.batch_sizes, [2, 2, 1])
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["source_pages"], [1, 2])
        self.assertEqual(items[1]["source_pages"], [3, 4])
        self.assertEqual(items[2]["source_pages"], [5])

    def test_vision_import_falls_back_to_markdown_for_invalid_page_json(self) -> None:
        class FakeVisionProvider:
            supports_vision = True

            def __init__(self) -> None:
                self.calls = 0

            async def complete_with_images(self, *, prompt: str, **kwargs):
                self.calls += 1
                content = (
                    "1. A sufficiently long transcribed physics question with $F=ma$."
                    if prompt.startswith("Transcribe")
                    else "not valid JSON"
                )
                return type("Response", (), {"content": content})()

        provider = FakeVisionProvider()
        asset = importer.SourceAsset(
            filename="page_001.png",
            payload=png_bytes(),
            page_number=1,
        )
        config = {
            "enabled": True,
            "configured": True,
            "supports_vision": True,
        }

        with (
            patch.object(importer, "llm_import_config", return_value=config),
            patch.object(importer, "get_llm_provider", return_value=provider),
        ):
            items = asyncio.run(
                importer._vision_split_into_file_questions(
                    page_assets=[asset],
                    ocr_page_texts=[],
                    original_filename="paper.pdf",
                )
            )

        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["metadata"]["human_review_needed"])
        self.assertEqual(
            items[0]["metadata"]["vision_fallback"],
            "page_markdown_transcription",
        )

    def test_multi_page_vision_import_only_skips_blanket_llm_review(self) -> None:
        self.assertTrue(
            importer._requires_review(
                source_type="pdf",
                import_method="llm_assisted",
                metadata={"human_review_needed": True},
                warnings=["figure needs cropping"],
                skip_llm_review=True,
            )
        )
        self.assertFalse(
            importer._requires_review(
                source_type="pdf",
                import_method="llm_assisted",
                metadata={"human_review_needed": False},
                warnings=[],
                skip_llm_review=True,
            )
        )
        self.assertTrue(
            importer._requires_review(
                source_type="pdf",
                import_method="llm_assisted",
                metadata={"human_review_needed": True},
                warnings=[],
            )
        )

    def test_multi_page_vision_import_routes_each_question_independently(self) -> None:
        source = self.root / "multi-page.pdf"
        source.write_bytes(b"fake pdf")
        page_assets = [
            importer.SourceAsset(
                filename=f"page_{page:03d}.png",
                payload=png_bytes(),
                page_number=page,
            )
            for page in (1, 2)
        ]
        llm_items = [
            {
                "question_body": "1. A complete text-only physics question.",
                "answer_body": "",
                "metadata": {
                    "source_pages": [1],
                    "human_review_needed": False,
                },
                "source_pages": [1],
            },
            {
                "question_body": "2. A question whose required figure needs manual cropping.",
                "answer_body": "",
                "metadata": {
                    "source_pages": [2],
                    "human_review_needed": True,
                },
                "source_pages": [2],
            },
        ]

        with (
            patch.object(importer, "_load_parser_modules"),
            patch.object(
                importer,
                "get_parser",
                return_value=lambda path: importer.ParsedDocument(raw_text=""),
            ),
            patch.object(importer, "_render_pdf_page_assets", return_value=page_assets),
            patch.object(importer, "_ocr_page_hints", return_value=[]),
            patch.object(
                importer,
                "_vision_split_into_file_questions",
                return_value=llm_items,
            ),
        ):
            result = asyncio.run(
                import_source_file(
                    source_path=source,
                    original_filename="multi-page.pdf",
                    use_llm_assist=True,
                    rebuild_after=False,
                )
            )

        self.assertEqual(len(result.questions), 1)
        self.assertEqual(len(result.candidates), 1)
        self.assertIn("complete text-only", result.questions[0].question_body)
        self.assertIn("required figure", result.candidates[0]["question_body"])

    def test_candidate_reimport_reuses_committed_review(self) -> None:
        source = self.root / "review.json"
        source.write_text(
            json.dumps(
                [
                    {
                        "question_body": "A reviewed source question.",
                        "metadata": {
                            "title": "Review",
                            "human_review_needed": True,
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )
        first = asyncio.run(
            import_source_file(
                source_path=source,
                original_filename="review.json",
                rebuild_after=False,
            )
        )
        candidate = first.candidates[0]
        approve_candidate(candidate["candidate_id"])

        second = asyncio.run(
            import_source_file(
                source_path=source,
                original_filename="review.json",
                rebuild_after=False,
            )
        )

        self.assertEqual(second.candidates, [])
        self.assertEqual(len(second.questions), 1)
        self.assertEqual(
            second.questions[0].question_id,
            candidate["proposed_question_id"],
        )

    def test_structured_items_with_same_title_get_distinct_stable_ids(self) -> None:
        source = self.root / "same-title.json"
        source.write_text(
            json.dumps(
                [
                    {
                        "question_body": "First source question.",
                        "metadata": {"title": "Same", "source_pages": [1]},
                    },
                    {
                        "question_body": "Second source question.",
                        "metadata": {"title": "Same", "source_pages": [1]},
                    },
                ]
            ),
            encoding="utf-8",
        )
        result = asyncio.run(
            import_source_file(
                source_path=source,
                original_filename="same-title.json",
                rebuild_after=False,
            )
        )

        self.assertEqual(len(result.questions), 2)
        self.assertEqual(len({item.question_id for item in result.questions}), 2)

    def test_export_manifest_and_missing_asset_gate(self) -> None:
        store.write_question(
            question_id="qf_export",
            question_body="Find $v$.\n\n![diagram](assets/diagram.png)",
            answer_body="$v=at$.",
            metadata={"title": "Export"},
            assets=[("diagram.png", png_bytes())],
        )
        store.rebuild_index()
        result = asyncio.run(
            file_api.export_file_paper(
                file_api.FilePaperRequest(
                    title="Regression Paper",
                    question_ids=["qf_export"],
                    question_count=1,
                )
            )
        )
        output = self.exports_dir / "file-papers" / result.export_id
        self.assertEqual(result.status, "tex_only")
        self.assertTrue((output / "questions.tex").is_file())
        self.assertTrue((output / "answers.tex").is_file())
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["questions"][0]["question_id"], "qf_export")
        self.assertEqual(manifest["questions"][0]["assets"][0]["filename"], "diagram.png")
        self.assertFalse(any((output.parent / ".staging").iterdir()))

        store.write_question(
            question_id="qf_missing_asset",
            question_body="![missing](assets/missing.png)",
            metadata={"title": "Broken"},
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                file_api.export_file_paper(
                    file_api.FilePaperRequest(
                        title="Broken Paper",
                        question_ids=["qf_missing_asset"],
                        question_count=1,
                    )
                )
            )
        self.assertEqual(raised.exception.status_code, 409)


class SkillMaterializerTest(unittest.TestCase):
    def test_same_title_records_resolve_to_distinct_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            questions = root / "questions"
            records_path = root / "questions.json"
            records_path.write_text(
                json.dumps(
                    [
                        {
                            "question_body": "First question.",
                            "metadata": {"title": "Same", "source_pages": [1]},
                        },
                        {
                            "question_body": "Second question.",
                            "metadata": {"title": "Same", "source_pages": [1]},
                        },
                    ]
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(SKILL_MATERIALIZER),
                str(records_path),
                "--questions-dir",
                str(questions),
                "--source-name",
                "paper.pdf",
                "--source-hash",
                "c" * 64,
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(questions.glob("qf_*"))), 2)

    def test_review_gate_stable_id_and_batch_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            questions = root / "questions"
            assets = root / "assets"
            assets.mkdir()
            (assets / "figure.png").write_bytes(png_bytes())
            records_path = root / "questions.json"
            records = [
                {
                    "question_body": "Find $v$.\\n\\n![figure](assets/figure.png)",
                    "answer_body": "$v=at$.",
                    "metadata": {
                        "title": "Motion",
                        "knowledge_points": ["kinematics"],
                        "source_pages": [1],
                        "human_review_needed": True,
                    },
                }
            ]
            records_path.write_text(json.dumps(records), encoding="utf-8")
            command = [
                sys.executable,
                str(SKILL_MATERIALIZER),
                str(records_path),
                "--questions-dir",
                str(questions),
                "--assets-root",
                str(assets),
                "--source-name",
                "paper.pdf",
                "--source-hash",
                "b" * 64,
            ]
            blocked = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("human_review_needed=true", blocked.stderr)
            self.assertFalse(any(questions.glob("qf_*")))

            approved = subprocess.run(
                [*command, "--approve-review"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)
            first_ids = sorted(path.name for path in questions.glob("qf_*"))
            self.assertEqual(len(first_ids), 1)

            repeated = subprocess.run(
                [*command, "--approve-review"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(first_ids, sorted(path.name for path in questions.glob("qf_*")))

            records.append(
                {
                    "question_body": "Second ![missing](assets/missing.png)",
                    "answer_body": "",
                    "metadata": {
                        "title": "Missing",
                        "knowledge_points": [],
                        "human_review_needed": False,
                    },
                }
            )
            records_path.write_text(json.dumps(records), encoding="utf-8")
            failed = subprocess.run(
                [*command, "--approve-review"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(first_ids, sorted(path.name for path in questions.glob("qf_*")))


if __name__ == "__main__":
    unittest.main()
