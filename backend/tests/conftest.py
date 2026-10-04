"""Test-only runtime settings.

The production default is the Docker sandbox.  The test suite opts into the
explicitly unsafe local subprocess mode so it stays deterministic on hosts
where Docker Desktop is not running.
"""

import os


os.environ.setdefault("LLM_MOCK", "1")
# Starlette's TestClient sends "Host: testserver".
os.environ.setdefault("ALLOWED_HOSTS", '["localhost","127.0.0.1","::1","testserver"]')
os.environ.setdefault("SANDBOX_MODE", "process")
os.environ.setdefault("ALLOW_UNSAFE_PROCESS_SANDBOX", "1")
