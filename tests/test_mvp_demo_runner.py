import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.mvp_demo_runner import run_mvp_demo


class MVPDemoRunnerTests(unittest.TestCase):
    def test_run_mvp_demo_exports_docx_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            output_dir = Path(tmp) / "outputs" / "demo"
            self._write_demo_dataset(data_dir)

            report = run_mvp_demo(
                data_dir=data_dir,
                output_dir=output_dir,
                case_id="g-demo",
                chunks_per_source=1,
            )

            self.assertTrue(report["evaluation"]["passed"], report)
            self.assertEqual(report["package_status"], "approved")
            self.assertEqual(report["retrieved_chunk_ids"], ["python-functions-c001", "ncs-demo-c001"])
            self.assertTrue(Path(report["docx_path"]).exists())
            self.assertTrue(Path(report["report_path"]).exists())
            saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["case_id"], "g-demo")

    def _write_demo_dataset(self, data_dir: Path) -> None:
        processed = data_dir / "processed"
        gold = data_dir / "gold"
        raw_curriculum = data_dir / "raw" / "curriculum"
        raw_ncs = data_dir / "raw" / "ncs"
        processed.mkdir(parents=True)
        gold.mkdir(parents=True)
        raw_curriculum.mkdir(parents=True)
        raw_ncs.mkdir(parents=True)

        chunks = [
            {
                "chunk_id": "python-functions-c001",
                "source_id": "python-functions",
                "source_name": "Python Tutorial - Defining Functions",
                "source_url": "https://docs.python.org/3/tutorial/controlflow.html",
                "license": "PSF",
                "section": "Functions",
                "source_file": "data/raw/materials/tutorial_functions.md",
                "text": "Python function def return practice.",
                "char_count": 36,
                "token_estimate": 9,
                "tags": ["python", "function", "def", "return"],
                "review_status": "needs_review",
            },
            {
                "chunk_id": "ncs-demo-c001",
                "source_id": "ncs-demo",
                "source_name": "NCS Demo",
                "source_url": "https://www.ncs.go.kr/",
                "license": "NCS",
                "section": "NCS Demo",
                "source_file": "data/raw/ncs/converted_md/ncs-demo.md",
                "text": "NCS 실습 시나리오 수행 절차 제출물 평가 기준.",
                "char_count": 30,
                "token_estimate": 8,
                "tags": ["NCS", "assessment"],
                "review_status": "needs_review",
            },
        ]
        with (processed / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as file:
            for row in chunks:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

        self._write_yaml(
            gold / "generation_gold.yaml",
            {
                "cases": [
                    {
                        "case_id": "g-demo",
                        "input": {
                            "curriculum_id": "curr-demo",
                            "ncs_unit_id": "2001020231",
                            "source_ids": ["python-functions", "ncs-demo"],
                        },
                        "expected": {
                            "lesson_plan_sections": ["도입", "전개", "정리"],
                            "practice_required": ["실습 시나리오", "수행 절차", "제출물", "평가 기준"],
                            "assessment_required": {"mcq_count": 5, "performance_task_count": 1},
                            "citation_required": True,
                        },
                    }
                ]
            },
        )
        self._write_yaml(
            raw_curriculum / "curriculum_python_prompt_automation.yaml",
            {
                "course_title": "생성형 AI 활용 Python 기초",
                "lesson_title": "Python 함수 자동화 실습",
                "learner_profile": "직업훈련 수강생",
                "learning_objectives": ["Python 함수를 활용해 자동화 실습을 수행할 수 있다."],
            },
        )
        self._write_yaml(
            raw_ncs / "ncs_application_sw_programming.yaml",
            {
                "selected_units": [
                    {
                        "unit_code": "2001020231",
                        "unit_name": "프로그래밍 언어 활용",
                        "learning_topics": ["스크립트 언어 활용"],
                    }
                ]
            },
        )

    def _write_yaml(self, path: Path, data) -> None:
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
