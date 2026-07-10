import re
from harness.models import ToolResult, TestFeedback

class TestRunner:
    # Individual FAILED/ERROR lines from pytest's short-test-summary section.
    FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(.+)$", re.M)

    def parse(self, tool_result: ToolResult) -> TestFeedback:
        out = (tool_result.output or {}).get("stdout", "") or ""
        m = re.search(r"(\d+)\s*passed", out, re.I)
        f = re.search(r"(\d+)\s*failed", out, re.I)
        e = re.findall(self.FAILED_LINE, out)
        passed = int(m.group(1)) if m else 0
        failed = int(f.group(1)) if f else 0
        if m is None and f is None and not e:
            return TestFeedback(0, 0, [], out)  # unparseable → raw, no crash
        return TestFeedback(passed=passed, failed=failed, errors=e, raw_output=out)