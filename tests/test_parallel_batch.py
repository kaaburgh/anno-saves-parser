import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anno_save_probe as probe


def state(name):
    return {
        "schema": probe.CANONICAL_SCHEMA,
        "schema_version": probe.CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": name},
        "sessions": [],
    }


class RecordingProgress:
    def __init__(self):
        self.messages = []

    def say(self, message):
        self.messages.append(message)

    def maybe(self, message):
        self.messages.append(message)

    def begin_parse(self, message):
        self.messages.append(message)

    def finish_parse(self, message):
        self.messages.append(message)

    def abort_parse(self, message):
        self.messages.append(message)


class FakeFuture:
    def __init__(self, result=None, exc=None, sort_key=""):
        self._result = result
        self._exc = exc
        self.sort_key = sort_key
        self.cancelled = False

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result

    def cancel(self):
        self.cancelled = True
        return True


class FakeExecutor:
    instances = []

    def __init__(self, max_workers):
        self.max_workers = max_workers
        self.submitted = []
        self.shutdown_calls = []
        self.__class__.instances.append(self)

    def submit(self, fn, save_path):
        try:
            result = fn(save_path)
            future = FakeFuture(result=result, sort_key=save_path)
        except BaseException as exc:
            future = FakeFuture(exc=exc, sort_key=save_path)
        self.submitted.append(future)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


def reverse_wait_factory(observed_sizes):
    def reverse_wait(futures, timeout, return_when):
        observed_sizes.append(len(futures))
        chosen = max(futures, key=lambda future: future.sort_key)
        return {chosen}, set(futures) - {chosen}
    return reverse_wait


class WorkerPolicyTests(unittest.TestCase):
    def test_resolved_workers_are_bounded_by_save_count(self):
        self.assertEqual(probe.resolve_worker_count(4, 2), 2)
        self.assertEqual(probe.resolve_worker_count(1, 20), 1)

    def test_resource_plan_warns_without_overriding_explicit_workers(self):
        progress = RecordingProgress()
        disk = type("Disk", (), {"free": 100 * 1024 * 1024})()
        with (
            patch.object(probe.os, "cpu_count", return_value=1),
            patch.object(probe, "_available_memory_bytes", return_value=100 * 1024 * 1024),
            patch.object(probe.shutil, "disk_usage", return_value=disk),
        ):
            probe.report_worker_plan(4, 4, progress)

        text = "\n".join(progress.messages)
        self.assertIn("requested=4 active=4 mode=process", text)
        self.assertIn("exceed logical CPUs", text)
        self.assertIn("available RAM", text)
        self.assertIn("free temp space", text)

    def test_posix_available_memory_uses_sysconf(self):
        values = {"SC_PAGE_SIZE": 4096, "SC_AVPHYS_PAGES": 1024}
        with (
            patch.object(probe.os, "name", "posix"),
            patch.object(
                probe.os,
                "sysconf",
                side_effect=lambda key: values[key],
                create=True,
            ),
        ):
            self.assertEqual(probe._available_memory_bytes(), 4 * 1024 * 1024)


class ParallelBatchTests(unittest.TestCase):
    def setUp(self):
        FakeExecutor.instances.clear()

    def test_parallel_completion_order_does_not_reorder_states_or_files(self):
        saves = [Path(f"Autosave {n}.a7s") for n in (1, 2, 3)]
        progress = RecordingProgress()
        wait_sizes = []

        def fake_worker(save_path):
            name = Path(save_path).name
            return state(name), float(int(Path(save_path).stem.split()[-1]))

        with tempfile.TemporaryDirectory() as td, patch.object(
            probe, "_canonicalize_worker", side_effect=fake_worker
        ):
            output = Path(td)
            states = probe.parse_saves_parallel(
                saves,
                output,
                progress,
                workers=2,
                executor_factory=FakeExecutor,
                wait_fn=reverse_wait_factory(wait_sizes),
            )

            self.assertEqual(
                [item["source"]["save_name"] for item in states],
                [save.name for save in saves],
            )
            for save in saves:
                path = output / f"{save.stem.replace(' ', '_')}.canonical.json.gz"
                self.assertTrue(path.exists())
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    self.assertEqual(json.load(stream)["source"]["save_name"], save.name)

        self.assertTrue(wait_sizes)
        self.assertLessEqual(max(wait_sizes), 2)
        self.assertEqual(FakeExecutor.instances[0].max_workers, 2)
        completion_lines = [m for m in progress.messages if m.startswith("[parse ") and "done" in m]
        self.assertEqual(len(completion_lines), 3)
        self.assertTrue(completion_lines[0].startswith("[parse 2/3]"))

    def test_parallel_failure_names_the_save_and_cancels_remaining_work(self):
        saves = [Path("Autosave 1.a7s"), Path("Autosave 2.a7s"), Path("Autosave 3.a7s")]
        progress = RecordingProgress()

        def fake_worker(save_path):
            name = Path(save_path).name
            if name == "Autosave 2.a7s":
                raise ValueError("synthetic failure")
            return state(name), 0.1

        with tempfile.TemporaryDirectory() as td, patch.object(
            probe, "_canonicalize_worker", side_effect=fake_worker
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Autosave 2.a7s: parallel parse failed: ValueError: synthetic failure",
            ):
                probe.parse_saves_parallel(
                    saves,
                    Path(td),
                    progress,
                    workers=2,
                    executor_factory=FakeExecutor,
                    wait_fn=reverse_wait_factory([]),
                )

        executor = FakeExecutor.instances[0]
        self.assertIn((True, True), executor.shutdown_calls)
        self.assertTrue(any(future.cancelled for future in executor.submitted))

    def test_workers_one_uses_existing_serial_path(self):
        saves = [Path("Autosave 1.a7s"), Path("Autosave 2.a7s")]
        progress = RecordingProgress()
        states = [state(save.name) for save in saves]

        with tempfile.TemporaryDirectory() as td, patch.object(
            probe, "canonicalize_save", side_effect=states
        ):
            result = probe.parse_saves_batch(saves, Path(td), progress, workers=1)

        self.assertEqual(result, states)
        self.assertTrue(any(message.startswith("[parse 1/2]") for message in progress.messages))
        self.assertTrue(any(message.startswith("[parse 2/2]") for message in progress.messages))


if __name__ == "__main__":
    unittest.main(verbosity=2)
