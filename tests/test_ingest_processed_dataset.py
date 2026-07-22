import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.ingest_processed_dataset import _upsert_with_retry, _write_checkpoint


class FlakyStore:
    def __init__(self) -> None:
        self.calls = 0

    def upsert(self, *, project_id, chunks):
        self.calls += 1
        if self.calls < 3:
            raise RuntimeError("temporary failure")


class IngestProcessedDatasetTests(unittest.TestCase):
    def test_upsert_retries_transient_batch_failure(self):
        store = FlakyStore()

        with patch("scripts.ingest_processed_dataset.time.sleep") as sleep:
            _upsert_with_retry(
                vector_store=store,
                project_id="mvp-dataset",
                chunks=[object()],
                max_retries=3,
                retry_delay=0.5,
            )

        self.assertEqual(store.calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

    def test_checkpoint_records_next_resume_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"

            _write_checkpoint(
                checkpoint,
                chunks_path=Path(tmp) / "chunks.jsonl",
                project_id="mvp-dataset",
                next_start_at=512,
                status="running",
            )

            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(payload["next_start_at"], 512)
            self.assertEqual(payload["status"], "running")


if __name__ == "__main__":
    unittest.main()
