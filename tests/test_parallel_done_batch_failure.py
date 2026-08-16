import tempfile
import unittest
from pathlib import Path

import anno_save_probe as probe


def state(name):
    return {
        "schema": probe.CANONICAL_SCHEMA,
        "schema_version": probe.CANONICAL_SCHEMA_VERSION,
        "source": {"save_name": name},
        "sessions": [],
    }


class Future:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.cancelled = False

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result

    def cancel(self):
        self.cancelled = True
        return True


class Progress:
    def say(self, message):
        pass

    def maybe(self, message):
        pass


class ParallelDoneBatchFailureTests(unittest.TestCase):
    def test_completed_failure_is_checked_before_pool_refill(self):
        saves = [Path(f"Autosave {n}.a7s") for n in (1, 2, 3)]
        success = Future(result=(state(saves[0].name), 0.1))
        failure = Future(exc=ValueError("synthetic failure"))

        class Executor:
            instance = None

            def __init__(self, max_workers):
                self.max_workers = max_workers
                self.submitted = []
                self.shutdown_calls = []
                Executor.instance = self

            def submit(self, fn, save_path):
                self.submitted.append(save_path)
                if save_path.endswith("1.a7s"):
                    return success
                if save_path.endswith("2.a7s"):
                    return failure
                return Future(result=(state(Path(save_path).name), 0.1))

            def shutdown(self, wait=True, cancel_futures=False):
                self.shutdown_calls.append((wait, cancel_futures))

        first_wait = True

        def wait_fn(futures, timeout, return_when):
            nonlocal first_wait
            if first_wait:
                first_wait = False
                return {success, failure}, set()
            return set(futures), set()

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(
                RuntimeError,
                "Autosave 2.a7s: parallel parse failed: ValueError: synthetic failure",
            ):
                probe.parse_saves_parallel(
                    saves,
                    Path(td),
                    Progress(),
                    workers=2,
                    executor_factory=Executor,
                    wait_fn=wait_fn,
                )

        self.assertEqual(Executor.instance.submitted, [str(saves[0]), str(saves[1])])
        self.assertIn((True, True), Executor.instance.shutdown_calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
