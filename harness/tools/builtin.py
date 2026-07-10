import subprocess
from harness.tools.base import ToolRegistry
from harness.models import ToolResult

def register_builtins(registry: ToolRegistry, config=None, workspace: str = ".") -> None:
    def read_file(args):
        p = args["path"]
        try:
            content = open(p, "r", encoding="utf-8").read()
            return ToolResult(ok=True, output={"content": content, "bytes": len(content.encode())})
        except FileNotFoundError:
            return ToolResult(ok=False, output={}, error=f"not found: {p}")
        except OSError as e:
            return ToolResult(ok=False, output={}, error=f"{e}")

    def write_file(args):
        p, content = args["path"], args["content"]
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(ok=True, output={"bytes_written": len(content.encode())})
        except OSError as e:
            return ToolResult(ok=False, output={}, error=f"{e}")

    def run_shell(args):
        cmd = args["command"]
        try:
            proc = subprocess.run(cmd, shell=True, cwd=workspace,
                                  capture_output=True, text=True, timeout=60)
            return ToolResult(ok=proc.returncode == 0,
                              output={"stdout": proc.stdout, "stderr": proc.stderr,
                                      "exit_code": proc.returncode, "command": cmd})
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output={"command": cmd}, error="timeout after 60s")

    def run_tests(args):
        cmd = (config.tests.command if config else args.get("test_cmd", "pytest -q"))
        try:
            proc = subprocess.run(cmd, shell=True, cwd=workspace,
                                  capture_output=True, text=True, timeout=120)
            return ToolResult(ok=proc.returncode == 0,
                              output={"command": cmd, "stdout": proc.stdout + proc.stderr,
                                      "exit_code": proc.returncode})
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output={"command": cmd}, error="test timeout 120s")

    registry.register("read_file", {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}, read_file)
    registry.register("write_file", {"name": "write_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}, write_file)
    registry.register("run_shell", {"name": "run_shell", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}, run_shell)
    registry.register("run_tests", {"name": "run_tests", "parameters": {"type": "object"}}, run_tests)