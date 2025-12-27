from __future__ import annotations

import asyncio
import errno
import os
import shlex
from logging import getLogger
from pathlib import PurePosixPath
from typing import ClassVar, Union

import modal
import modal.exception
from inspect_ai.util import (
    ExecResult,
    OutputLimitExceededError,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentLimits,
    sandboxenv,
)
from typing_extensions import override

logger = getLogger(__name__)

MODAL_APP_NAME = "inspect-modal-sandbox"


@sandboxenv(name="modal")
class ModalSandboxEnvironment(SandboxEnvironment):
    """Modal sandbox environment for running code in Modal containers."""

    sandbox: modal.Sandbox
    working_dir: str
    image_cache: ClassVar[dict[str, modal.Image]] = {}

    def __init__(self, sandbox: modal.Sandbox, working_dir: str = "/") -> None:
        super().__init__()
        self.sandbox = sandbox
        self.working_dir = working_dir

    @override
    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        if isinstance(config, str):
            cls._get_or_build_image(config)

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        app = modal.App.lookup(MODAL_APP_NAME, create_if_missing=True)

        # Build or retrieve image
        image: modal.Image | None = None
        if isinstance(config, str):
            image = cls._get_or_build_image(config)

        # Create sandbox
        sandbox = modal.Sandbox.create(
            app=app,
            image=image,
            timeout=60 * 60,  # 1 hour default timeout
        )

        # Get working directory
        working_dir = "/"
        try:
            result = sandbox.exec("pwd")
            stdout = result.stdout.read()
            if stdout:
                working_dir = stdout.strip()
        except Exception:
            pass

        return {"default": ModalSandboxEnvironment(sandbox, working_dir)}

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        if not interrupted:
            for env in environments.values():
                modal_env = env.as_type(ModalSandboxEnvironment)
                try:
                    modal_env.sandbox.terminate()
                except Exception as e:
                    logger.warning(f"Error terminating Modal sandbox: {e}")

    @override
    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        if cleanup:
            cls.image_cache.clear()

    @classmethod
    def _get_or_build_image(cls, config: str) -> modal.Image:
        if config in cls.image_cache:
            return cls.image_cache[config]

        if not os.path.isfile(config):
            raise FileNotFoundError(f"Dockerfile not found: {config}")

        image = modal.Image.from_dockerfile(config)
        cls.image_cache[config] = image
        return image

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
        # Resolve working directory
        if cwd is None:
            workdir = self.working_dir
        else:
            path = PurePosixPath(cwd)
            if path.is_absolute():
                workdir = str(path)
            else:
                workdir = str(PurePosixPath(self.working_dir) / path)

        # Handle user parameter by wrapping with su
        if user is not None:
            # Wrap command with su to run as specified user
            cmd_str = shlex.join(cmd)
            cmd = ["su", "-s", "/bin/sh", "-c", cmd_str, user]

        def _run_exec_sync() -> ExecResult[str]:
            # Execute command
            process = self.sandbox.exec(
                *cmd,
                workdir=workdir,
                env=env if env else None,  # type: ignore
            )

            # Handle stdin if provided
            if input is not None:
                if isinstance(input, str):
                    process.stdin.write(input.encode("utf-8"))
                else:
                    process.stdin.write(input)
                process.stdin.write_eof()
                process.stdin.drain()

            # Read output
            stdout = process.stdout.read()
            stderr = process.stderr.read()

            # Wait for completion and get return code
            process.wait()
            returncode = process.returncode or 0

            # Check output size limits
            stdout_bytes = len(stdout.encode("utf-8"))
            stderr_bytes = len(stderr.encode("utf-8"))
            max_size = SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE

            if stdout_bytes > max_size or stderr_bytes > max_size:
                raise OutputLimitExceededError(
                    limit_str=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR,
                    truncated_output=stdout[:max_size]
                    if stdout_bytes > max_size
                    else stdout,
                )

            # Check for permission error
            if returncode == 126:
                raise PermissionError(f"Permission denied executing command: {cmd}")

            return ExecResult(
                success=returncode == 0,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

        try:
            # Run blocking Modal operations in thread pool, apply timeout
            if timeout is not None:
                return await asyncio.wait_for(
                    asyncio.to_thread(_run_exec_sync), timeout=timeout
                )
            else:
                return await asyncio.to_thread(_run_exec_sync)

        except asyncio.TimeoutError:
            raise TimeoutError(f"Command timed out after {timeout} seconds")
        except TimeoutError:
            raise
        except PermissionError:
            raise
        except OutputLimitExceededError:
            raise
        except (
            modal.exception.SandboxTimeoutError,
            modal.exception.ExecTimeoutError,
        ):
            raise TimeoutError(f"Command timed out after {timeout} seconds")
        except Exception as e:
            # Log unexpected errors
            logger.error(f"Unexpected error executing command: {e}")
            raise

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        # Resolve path
        path = PurePosixPath(file)
        if not path.is_absolute():
            path = PurePosixPath(self.working_dir) / path
        file_path = str(path)

        # Ensure parent directory exists
        parent = str(path.parent)
        if parent and parent != "/":
            try:
                self.sandbox.mkdir(parent, parents=True)
            except Exception:
                pass  # Directory might already exist

        try:
            # Write file
            mode = "w" if isinstance(contents, str) else "wb"
            with self.sandbox.open(file_path, mode) as f:  # type: ignore
                f.write(contents)
        except Exception as e:
            error_str = str(e).lower()
            if "permission denied" in error_str:
                raise PermissionError(errno.EACCES, "Permission denied", file)
            elif "is a directory" in error_str:
                raise IsADirectoryError(
                    errno.EISDIR, f"Cannot write to {file} because it is a directory"
                )
            raise

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:  # type: ignore
        # Resolve path
        path = PurePosixPath(file)
        if not path.is_absolute():
            path = PurePosixPath(self.working_dir) / path
        file_path = str(path)

        def _is_directory(path: str) -> bool:
            try:
                process = self.sandbox.exec("test", "-d", path)
                process.wait()
                return process.returncode == 0
            except Exception:
                return False

        try:
            mode = "r" if text else "rb"
            with self.sandbox.open(file_path, mode) as f:  # type: ignore
                contents = f.read()

            # Check size limit
            content_size = len(
                contents.encode("utf-8") if isinstance(contents, str) else contents
            )
            if content_size > SandboxEnvironmentLimits.MAX_READ_FILE_SIZE:
                raise OutputLimitExceededError(
                    limit_str=SandboxEnvironmentLimits.MAX_READ_FILE_SIZE_STR,
                    truncated_output=None,
                )

            return contents

        except FileNotFoundError:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", file)
        except OutputLimitExceededError:
            raise
        except IsADirectoryError:
            raise
        except modal.exception.FilesystemExecutionError:
            # Check if it's a directory
            if _is_directory(file_path):
                raise IsADirectoryError(errno.EISDIR, "Is a directory", file)
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", file)
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "no such file" in error_str:
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", file)
            elif "permission denied" in error_str:
                raise PermissionError(errno.EACCES, "Permission denied", file)
            elif "is a directory" in error_str:
                raise IsADirectoryError(errno.EISDIR, "Is a directory", file)
            # Check if it's a directory as a fallback
            if _is_directory(file_path):
                raise IsADirectoryError(errno.EISDIR, "Is a directory", file)
            raise
