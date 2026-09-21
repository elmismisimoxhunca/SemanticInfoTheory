from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import resume_throttled_orchestrator as orchestrator


class ResourceGateTests(unittest.TestCase):
    def test_disk_space_is_part_of_resource_decision(self) -> None:
        self.assertFalse(
            orchestrator.resources_available(
                load1=1.0,
                cores=8,
                available_mib=6144.0,
                free_bytes=15 * 1024**3,
                minimum_free_bytes=16 * 1024**3,
            )
        )
        self.assertTrue(
            orchestrator.resources_available(
                load1=1.0,
                cores=8,
                available_mib=6144.0,
                free_bytes=16 * 1024**3,
                minimum_free_bytes=16 * 1024**3,
            )
        )


class StoreCleanupTests(unittest.TestCase):
    def test_validated_surface_allows_scratch_store_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            surface = root / "surface.json"
            store = root / "surface.store"
            log = root / "resource.log"
            surface.write_text("{}\n", encoding="utf-8")
            store.write_bytes(b"scratch")

            orchestrator.finalize_completed_run(
                surface=surface,
                store=store,
                run_id="run-1",
                item_label="track_a:run-1",
                validator=lambda path, run_id: path == surface and run_id == "run-1",
                log_path=log,
            )

            self.assertFalse(store.exists())
            self.assertIn("store_cleanup", log.read_text(encoding="utf-8"))

    def test_invalid_surface_preserves_store_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            surface = root / "surface.json"
            store = root / "surface.store"
            log = root / "resource.log"
            surface.write_text("{}\n", encoding="utf-8")
            store.write_bytes(b"scratch")

            with self.assertRaisesRegex(RuntimeError, "completed surface validation failed"):
                orchestrator.finalize_completed_run(
                    surface=surface,
                    store=store,
                    run_id="run-1",
                    item_label="track_a:run-1",
                    validator=lambda _path, _run_id: False,
                    log_path=log,
                )

            self.assertTrue(store.exists())


if __name__ == "__main__":
    unittest.main()
