import json
import subprocess
import sys
import tempfile
from typing import Any

import pandas as pd


class SandboxError(Exception):
    pass


def run_rule(code: str, df: pd.DataFrame, timeout_s: int = 20) -> list:
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
