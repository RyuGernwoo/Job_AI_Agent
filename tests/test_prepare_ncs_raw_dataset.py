import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.prepare_ncs_raw_dataset import (
    latest_ncs_code_year,
    prepare_dataset,
    read_markdown,
    source_title,
    xls_chunks,
)


class PrepareNcsRawDatasetTests(unittest.TestCase):
    def test_source_title_removes_distribution_artifacts(self):
        self.assertEqual(
            source_title(
                Path("+2016년도+NCS+학습모듈+공적개발원조사업관리_개발전략수립_20170203수정.pdf"),
                ["사업관리"],
            ),
            "공적개발원조사업관리 개발전략수립",
        )
        self.assertEqual(
            source_title(Path("LM0301010102_예금상품세일즈.pdf"), ["금융_보험"]),
            "예금상품세일즈",
        )

    def test_latest_ncs_code_year_accepts_full_codes(self):
        self.assertEqual(latest_ncs_code_year(["0101010101_17v2", "0201010101_22v3"]), 2022)

    def test_pdf_is_converted_to_markdown_before_chunks_and_duplicate_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw_root = base / "NCS_raw"
            category = raw_root / "1. 사업관리" / "1. 프로젝트관리"
            category.mkdir(parents=True)
            source = category / "01. 범위관리_2020.pdf"
            duplicate = category / "01. 범위관리_2020 (1).pdf"
            self._write_pdf(source)
            shutil.copyfile(source, duplicate)

            report = prepare_dataset(
                raw_root=raw_root,
                markdown_root=base / "raw" / "converted_md",
                processed_root=base / "processed",
                chunk_size=500,
                chunk_overlap=50,
                force=True,
            )

            self.assertTrue(report["ready"])
            self.assertEqual(report["pdf_files"], 2)
            self.assertEqual(report["exact_duplicates_excluded_from_rag"], 1)
            markdown_files = list((base / "raw" / "converted_md").rglob("*.md"))
            self.assertEqual(len(markdown_files), 2)
            metadata, body = read_markdown(markdown_files[0])
            self.assertEqual(metadata["conversion_method"], "pymupdf")
            self.assertIn("## Page 1", body)

            chunk_rows = [
                json.loads(line)
                for line in (base / "processed" / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertGreaterEqual(len(chunk_rows), 1)
            self.assertTrue(all(row["source_type"] == "md" for row in chunk_rows))
            self.assertTrue(all(row["page"] == 1 for row in chunk_rows))
            self.assertTrue(all(row["metadata"]["original_source_type"] == "pdf" for row in chunk_rows))

    def test_xls_markdown_is_chunked_by_ability_unit(self):
        record = {
            "source_id": "ncs-src-test",
            "document_id": "ncs-xls-test",
            "source_name": "NCS 능력단위 보고서 - 프로젝트관리",
            "source_kind": "xls",
            "converted_markdown": "data/raw/ncs.md",
            "original_path": "data/NCS_raw/report.xls",
            "sha256": "abc",
            "ncs_hierarchy": ["사업관리", "프로젝트관리"],
            "top_category": "사업관리",
            "source_year": None,
        }
        body = """# report

## 능력단위: 010101_20v1

### Row 1

**능력단위 명칭:** 프로젝트 범위관리 계획을 수립하고 작업분류체계를 작성한다.

## 능력단위: 010102_20v1

### Row 2

**능력단위 명칭:** 프로젝트 일정과 자원을 계획하고 통제하는 수행준거를 정의한다.
"""

        chunks = list(xls_chunks(body=body, record=record, chunk_size=500, chunk_overlap=50))

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["metadata"]["ncs_unit_code"], "010101_20v1")
        self.assertEqual(chunks[1]["metadata"]["ncs_unit_code"], "010102_20v1")

    @staticmethod
    def _write_pdf(path: Path) -> None:
        document = fitz.open()
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "Project scope management defines requirements, work breakdown structure, and validation.",
        )
        document.new_page()
        document.save(path)
        document.close()


if __name__ == "__main__":
    unittest.main()
