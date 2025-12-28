from __future__ import annotations

import asyncio
import errno
import warnings
from logging import getLogger
from pathlib import PurePosixPath

import modal
import modal.exception
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentLimits,
    sandboxenv,
)
from inspect_ai.util._sandbox.limits import OutputLimitExceededError
from typing_extensions import override

logger = getLogger(__name__)

MODAL_APP_NAME = "inspect-modal-sandbox"


@sandboxenv(name="modal")
class ModalSandboxEnvironment(SandboxEnvironment):
    """Modal sandbox environment for running code in Modal containers."""

    def __init__(self, sandbox: modal.Sandbox) -> None:
        super().__init__()
        self.sandbox = sandbox

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        app = modal.App.lookup(MODAL_APP_NAME, create_if_missing=True)

        image = modal.Image.from_dockerfile(config) if isinstance(config, str) else None

        sandbox = modal.Sandbox.create(
            app=app,
            image=image,
            timeout=60 * 60,  # 1 hour
        )

        return {"default": cls(sandbox)}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        for env in environments.values():
            try:
                env.as_type(ModalSandboxEnvironment).sandbox.terminate()
            except Exception as e:
                logger.warning(f"Error terminating Modal sandbox: {e}")

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        if user is not None:
            warnings.warn(
                "The 'user' parameter is ignored in ModalSandboxEnvironment. "
                "Commands will run as the container's default user.",
                UserWarning,
            )

        # Modal requires absolute paths for workdir
        workdir = cwd
        if workdir is not None and not PurePosixPath(workdir).is_absolute():
            workdir = f"/{workdir}"

        def _run() -> ExecResult[str]:
            process = self.sandbox.exec(
                *cmd,
                workdir=workdir,
                env=env if env else None,
            )

            if input is not None:
                data = input.encode("utf-8") if isinstance(input, str) else input
                process.stdin.write(data)
                process.stdin.write_eof()
                process.stdin.drain()

            stdout = process.stdout.read()
            stderr = process.stderr.read()
            process.wait()

            return ExecResult(
                success=process.returncode == 0,
                returncode=process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )

        try:
            if timeout:
                result = await asyncio.wait_for(
                    asyncio.to_thread(_run), timeout=timeout
                )
            else:
                result = await asyncio.to_thread(_run)

            # Verify output limits
            self._verify_exec_result_size(result)
            return result

        except asyncio.TimeoutError:
            raise TimeoutError(f"Command timed out after {timeout} seconds")

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        # Ensure parent directory exists
        parent = str(PurePosixPath(file).parent)
        if parent and parent != "/" and parent != ".":
            try:
                self.sandbox.mkdir(parent, parents=True)
            except Exception:
                pass  # Directory may already exist

        mode = "w" if isinstance(contents, str) else "wb"
        with self.sandbox.open(file, mode) as f:
            f.write(contents)

    @override
    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        mode = "r" if text else "rb"
        try:
            with self.sandbox.open(file, mode) as f:
                contents = f.read()
        except FileNotFoundError:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", file)
        except IsADirectoryError:
            raise IsADirectoryError(errno.EISDIR, "Is a directory", file)
        except modal.exception.FilesystemExecutionError:
            # Fallback for unspecified errors
            if self._is_directory(file):
                raise IsADirectoryError(errno.EISDIR, "Is a directory", file)
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", file)

        # Verify size limit
        size = len(contents.encode("utf-8") if isinstance(contents, str) else contents)
        if size > SandboxEnvironmentLimits.MAX_READ_FILE_SIZE:
            raise OutputLimitExceededError(
                limit_str=SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR,
                truncated_output=None,
            )

        return contents

    def _is_directory(self, path: str) -> bool:
        """Check if path is a directory."""
        try:
            process = self.sandbox.exec("test", "-d", path)
            process.wait()
            return process.returncode == 0
        except Exception:
            return False

    def _verify_exec_result_size(self, result: ExecResult[str]) -> None:
        """Verify exec output doesn't exceed limits."""
        max_size = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE
        stdout_size = len(result.stdout.encode("utf-8"))
        stderr_size = len(result.stderr.encode("utf-8"))

        if stdout_size > max_size or stderr_size > max_size:
            raise OutputLimitExceededError(
                limit_str=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR,
                truncated_output=result.stdout[:max_size]
                if stdout_size > max_size
                else result.stdout,
            )
