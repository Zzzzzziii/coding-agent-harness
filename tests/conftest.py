# tests/conftest.py
class ScriptedTool:
    """Returns canned ToolResults in order. Used to script run_tests output so the
    real TestRunner parser stays exercised deterministically (no network/LLM)."""

    def __init__(self, results):
        self._results = list(results)
        self._i = 0

    def __call__(self, args):
        r = self._results[self._i]
        self._i += 1
        return r
