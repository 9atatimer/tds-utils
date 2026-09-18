"""OpSecrets -- SecretsPort over the 1Password CLI (``op read``), bounded by
its own timeout so a locked vault fails a run fast (Subsystem 3)."""

from __future__ import annotations

import subprocess

from chores.ports.errors import SecretUnavailable


class OpSecrets:
    def __init__(self, *, binary: str = "op") -> None:
        self._binary = binary

    def resolve(self, reference: str, *, timeout_sec: int) -> str:
        try:
            out = subprocess.run(
                [self._binary, "read", "--no-newline", reference],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as e:
            raise SecretUnavailable(f"op read timed out after {timeout_sec}s") from e
        except OSError as e:
            raise SecretUnavailable(f"op not runnable: {e}") from e
        if out.returncode != 0:
            raise SecretUnavailable(
                out.stderr.strip()[:200] or f"op exit {out.returncode}"
            )
        return out.stdout
