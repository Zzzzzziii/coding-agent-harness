# tests/unit/test_test_runner.py
from harness.feedback.test_runner import TestRunner
from harness.models import ToolResult

def make(stdout, exit_code=1):
    return ToolResult(ok=exit_code == 0, output={"stdout": stdout, "exit_code": exit_code, "command": "pytest"})

def test_parse_all_pass():
    tf = TestRunner().parse(make("==== 3 passed in 0.12s ====", exit_code=0))
    assert tf.passed == 3 and tf.failed == 0 and tf.success

def test_parse_failures():
    out = "FAILED tests/test_a.py::test_one\nFAILED tests/test_a.py::test_two\n==== 2 failed in 0.5s ===="
    tf = TestRunner().parse(make(out))
    assert tf.failed == 2 and not tf.success
    assert any("test_one" in e for e in tf.errors)

def test_parse_errors_and_skipped():
    out = ("ERROR tests/test_a.py::test_a\n"
           "ERROR tests/test_a.py::test_b\n"
           "==== 1 passed, 1 failed, 2 errors, 3 skipped in 1s ====")
    tf = TestRunner().parse(make(out))
    assert tf.passed == 1 and tf.failed == 1
    assert len(tf.errors) >= 2

def test_unparseable_returns_raw():
    tf = TestRunner().parse(make("totally not pytest output"))
    assert tf.passed == 0 and tf.failed == 0 and not tf.success
    assert tf.raw_output == "totally not pytest output"