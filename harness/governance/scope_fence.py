import os

class ScopeFence:
    def __init__(self, allowed_paths: list[str]):
        self.roots = [self._norm(p) for p in allowed_paths]

    @staticmethod
    def _norm(p: str) -> str:
        # realpath resolves symlinks + ../ traversal; normcase lowercases on Windows
        # (identity on POSIX) for case-insensitive comparison; path need not exist.
        return os.path.normcase(os.path.realpath(os.path.normpath(p)))

    def is_allowed(self, path: str) -> bool:
        rp = self._norm(path)
        return any(rp == r or rp.startswith(r + os.sep) for r in self.roots)