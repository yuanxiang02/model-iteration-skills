"""Platform primitives: locks, process identity, process trees, script argv."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from mih import _platform


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mih-lock-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "guard.lock"

    def test_second_handle_is_refused_when_non_blocking(self):
        with open(self.path, "a+") as first:
            _platform.lock(first, blocking=False)
            try:
                with open(self.path, "a+") as second:
                    with self.assertRaises(BlockingIOError):
                        _platform.lock(second, blocking=False)
            finally:
                _platform.unlock(first)

    def test_lock_is_released_for_the_next_holder(self):
        with open(self.path, "a+") as first:
            _platform.lock(first, blocking=False)
            _platform.unlock(first)
        with open(self.path, "a+") as second:
            _platform.lock(second, blocking=False)
            _platform.unlock(second)

    def test_blocking_lock_waits_for_the_release(self):
        acquired = threading.Event()
        released = threading.Event()

        def holder():
            with open(self.path, "a+") as handle:
                _platform.lock(handle, blocking=False)
                acquired.set()
                released.wait(5)
                _platform.unlock(handle)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(acquired.wait(5))

        def waiter():
            with open(self.path, "a+") as handle:
                _platform.lock(handle, blocking=True)
                _platform.unlock(handle)

        waiting = threading.Thread(target=waiter)
        waiting.start()
        time.sleep(0.2)
        self.assertTrue(waiting.is_alive(), "blocking lock returned while still held")
        released.set()
        waiting.join(10)
        thread.join(10)
        self.assertFalse(waiting.is_alive())


class IdentityTests(unittest.TestCase):
    def test_current_process_has_a_stable_identity(self):
        first = _platform.process_identity(os.getpid())
        second = _platform.process_identity(os.getpid())
        self.assertIsNotNone(first)
        self.assertEqual(first, second)

    def test_missing_pid_has_no_identity(self):
        self.assertIsNone(_platform.process_identity(0))
        self.assertIsNone(_platform.process_identity(None))

    def test_dead_process_has_no_identity(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.05)"],
            **_platform.spawn_kwargs(),
        )
        self.assertIsNotNone(_platform.process_identity(child.pid))
        child.wait(timeout=10)
        time.sleep(0.3)
        self.assertIsNone(_platform.process_identity(child.pid))


class TerminateTests(unittest.TestCase):
    def test_terminate_pid_stops_a_running_child(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            **_platform.spawn_kwargs(),
        )
        self.addCleanup(lambda: child.poll() is None and child.kill())
        _platform.terminate_pid(child.pid, force=True)
        self.assertIsNotNone(child.wait(timeout=15))


class ScriptArgvTests(unittest.TestCase):
    def test_python_file_uses_the_current_interpreter(self):
        argv = _platform.script_argv(Path("tool.py"), "--version")
        expected = [sys.executable, "tool.py", "--version"] if _platform.WINDOWS else ["tool.py", "--version"]
        self.assertEqual(argv, expected)

    def test_shebang_script_is_resolved_on_windows_only(self):
        with tempfile.TemporaryDirectory(prefix="mih-shebang-") as directory:
            script = Path(directory) / "dsh"
            script.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
            argv = _platform.script_argv(script, "--version")
        if _platform.WINDOWS:
            self.assertEqual(argv[0], sys.executable)
            self.assertEqual(argv[1], str(script))
        else:
            self.assertEqual(argv, [str(script), "--version"])

    def test_native_suffix_is_not_rewritten(self):
        argv = _platform.script_argv(Path("tool.exe"), "a")
        self.assertEqual(argv[0], "tool.exe")

    def test_argv_actually_runs(self):
        with tempfile.TemporaryDirectory(prefix="mih-argv-") as directory:
            script = Path(directory) / "probe.py"
            script.write_text(
                "#!/usr/bin/env python3\nimport sys\nprint('argv-ok', sys.argv[1])\n",
                encoding="utf-8",
            )
            if not _platform.WINDOWS:
                # POSIX needs an executable bit (and the shebang above) to exec directly.
                script.chmod(0o755)
            child = subprocess.run(
                _platform.script_argv(script, "x"), capture_output=True, text=True, timeout=60
            )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("argv-ok x", child.stdout)


class SystemLabelTests(unittest.TestCase):
    def test_label_is_non_empty_and_single_line(self):
        label = _platform.system_label()
        self.assertTrue(label.strip())
        self.assertNotIn("\n", label)


if __name__ == "__main__":
    unittest.main()
