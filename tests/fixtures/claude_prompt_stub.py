"""Fake CLI for transport tests only. Never contacts a provider."""
import json
import os
from pathlib import Path
import sys
import time

mode = os.environ.get("AX_PROMPT_TEST_MODE", "success")
if mode == "no_stdin":
    time.sleep(5)
    sys.exit(0)
prompt = sys.stdin.read()
log = os.environ.get("AX_PROMPT_TEST_LOG")
if log:
    with Path(log).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"prompt": prompt, "args": sys.argv[1:], "cwd": os.getcwd()}, ensure_ascii=False) + "\n")
if mode == "exit_error":
    print("PRIVATE_STDERR", file=sys.stderr)
    sys.exit(7)
if mode == "malformed":
    print("invalid output")
    sys.exit(0)
print(json.dumps({"type": "system", "subtype": "init", "model": "test-model"}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "thinking", "thinking": "PRIVATE_THINKING"},
    {"type": "text", "text": "개발 요청을 확인했습니다."}]}}, ensure_ascii=False), flush=True)
if mode == "delay":
    time.sleep(0.5)
if mode == "silent":
    time.sleep(5)
answer = "음수 입력 검증 조건을 확인했습니다. 소스 본문이 필요합니다. <script>alert(1)</script>"
if mode == "oversized":
    answer = "a" * 128001
if mode == "empty":
    answer = ""
print(json.dumps({"type": "result", "is_error": mode == "result_error", "result": answer}, ensure_ascii=False), flush=True)
