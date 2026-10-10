import atexit
import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SandboxError(Exception):
    pass


_daytona_sandbox = None
_daytona_client = None


def _get_daytona_sandbox():
    global _daytona_sandbox, _daytona_client

    if _daytona_sandbox is not None:
        return _daytona_sandbox

    api_key = os.environ.get("DAYTONA_API_KEY")
    if not api_key:
        return None

    try:
        from daytona import Daytona, CreateSandboxFromSnapshotParams

        _daytona_client = Daytona()
        params = CreateSandboxFromSnapshotParams(language="python")
        _daytona_sandbox = _daytona_client.create(params, timeout=60)

        # Install pandas
        _daytona_sandbox.process.exec("pip install pandas", timeout=120)

        # Register cleanup on process exit
        atexit.register(_cleanup_daytona_sandbox)

        logger.info(f"Created Daytona sandbox: {_daytona_sandbox.id}")
        return _daytona_sandbox
    except Exception as e:
        logger.warning(f"Failed to create Daytona sandbox, falling back to local: {e}")
        _daytona_client = None
        _daytona_sandbox = None
        return None


def _cleanup_daytona_sandbox():
    global _daytona_sandbox, _daytona_client

    if _daytona_sandbox is not None and _daytona_client is not None:
        try:
            _daytona_client.delete(_daytona_sandbox, wait=True)
            logger.info(f"Deleted Daytona sandbox: {_daytona_sandbox.id}")
        except Exception as e:
            logger.warning(f"Failed to delete Daytona sandbox: {e}")
        finally:
            _daytona_sandbox = None
            _daytona_client = None


def _run_rule_daytona(code: str, df: pd.DataFrame, timeout_s: int) -> list:
    sandbox = _get_daytona_sandbox()
    if sandbox is None:
        raise SandboxError("Daytona sandbox not available")

    try:
        # Upload dataframe as CSV
        csv_content = df.to_csv(index=False).encode()
        sandbox.fs.upload_file(csv_content, "data.csv")

        # Create runner script
        runner_script = f"""
import json
import pandas as pd

df = pd.read_csv("data.csv")

{code}

results = []
for _, row in df.iterrows():
    result = rule(row.to_dict())
    results.append(result)

print(json.dumps(results))
"""
        sandbox.fs.upload_file(runner_script.encode(), "runner.py")

        # Execute the runner
        response = sandbox.process.exec("python runner.py", timeout=timeout_s)

        if response.exit_code != 0:
            raise SandboxError(f"Daytona execution failed with exit code {response.exit_code}")

        return json.loads(response.artifacts.stdout)
    except Exception as e:
        logger.warning(f"Daytona execution failed, falling back to local: {e}")
        raise


def run_rule(code: str, df: pd.DataFrame, timeout_s: int = 20) -> list:
    # Try Daytona first if API key is set
    if os.environ.get("DAYTONA_API_KEY"):
        try:
            return _run_rule_daytona(code, df, timeout_s)
        except Exception as e:
            logger.warning(f"Daytona execution failed, falling back to local: {e}")

    # Fallback to local subprocess
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as csv_file:
        df.to_csv(csv_file.name, index=False)
        csv_path = csv_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as code_file:
        code_file.write(code)
        code_path = code_file.name

    script = f"""import json
import pandas as pd

df = pd.read_csv("{csv_path}")

with open("{code_path}") as f:
    exec(f.read())

results = []
for _, row in df.iterrows():
    result = rule(row.to_dict())
    results.append(result)

print(json.dumps(results))
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as script_file:
        script_file.write(script)
        script_path = script_file.name

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

        if result.returncode != 0:
            raise SandboxError(f"Rule execution failed: {result.stderr}")

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise SandboxError(f"Rule execution timed out after {timeout_s}s")
    except Exception as e:
        raise SandboxError(f"Rule execution error: {e}")
