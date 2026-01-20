from __future__ import annotations

import asyncio
import errno
import os
import sys
import warnings
from logging import getLogger
from pathlib import PurePosixPath
from typing import Any

import modal
import modal.exception
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentLimits,
    is_compose_yaml,
    is_dockerfile,
    parse_compose_yaml,
    sandboxenv,
)
from inspect_ai.util._sandbox.limits import OutputLimitExceededError
from rich import box, print
from rich.prompt import Confirm
from rich.table import Table
from typing_extensions import override

from ._compose import convert_compose_to_modal_params

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
        app = await modal.App.lookup.aio(MODAL_APP_NAME, create_if_missing=True)

        # Default parameters
        sandbox_params: dict[str, Any] = {
            "app": app,
            "timeout": 60 * 60 * 24,  # 24 hours (maximum lifetime)
        }

        if isinstance(config, str):
            if is_compose_yaml(config):
                compose_config = parse_compose_yaml(
                    config,
                    multiple_services=False,
                )
                modal_params = convert_compose_to_modal_params(compose_config, config)
                sandbox_params.update(modal_params)
            elif is_dockerfile(config):
                sandbox_params["image"] = modal.Image.from_dockerfile(config)
            else:
                raise ValueError(
                    f"Unrecognized config file: {config}. "
                    "Expected a compose file (compose.yaml) or Dockerfile."
                )

        sandbox = await modal.Sandbox.create.aio(**sandbox_params)
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
                sandbox = env.as_type(ModalSandboxEnvironment).sandbox
                await sandbox.terminate.aio()
            except Exception as e:
                logger.warning(f"Error terminating Modal sandbox: {e}")

    @override
    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        if id is not None:
            try:
                sandbox = await modal.Sandbox.from_id.aio(id)
                await sandbox.terminate.aio()
            except Exception as e:
                print(f"Error terminating sandbox {id}: {e}")
        else:
            sandboxes = [sb async for sb in modal.Sandbox.list.aio()]

            if not sandboxes:
                print("No Modal sandboxes found to clean up.")
                return

            table = Table(
                box=box.SQUARE,
                show_lines=False,
                title_style="bold",
                title_justify="left",
            )
            table.add_column("Sandbox ID")
            for sb in sandboxes:
                table.add_row(sb.object_id)
            print(table)

            # Borrowed from the proxmox provider - only prompt if in an interactive shell  # noqa: E501
            is_interactive = sys.stdin.isatty()
            is_ci = "CI" in os.environ
            is_pytest = "PYTEST_CURRENT_TEST" in os.environ

            if is_interactive and not is_ci and not is_pytest:
                if not Confirm.ask(
                    f"Are you sure you want to terminate ALL {len(sandboxes)} "
                    "sandbox(es) above?"
                ):
                    print("Cancelled.")
                    return

            for sb in sandboxes:
                try:
                    await sb.terminate.aio()
                except Exception as e:
                    print(f"Error terminating sandbox: {e}")
            print("Complete.")

    @classmethod
    def config_files(cls) -> list[str]:
        return [
            "compose.yaml",
            "compose.yml",
            "docker-compose.yaml",
            "docker-compose.yml",
            "Dockerfile",
        ]

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

        async def _run() -> ExecResult[str]:
            process = await self.sandbox.exec.aio(
                *cmd,
                workdir=workdir,
                env=env if env else None,
            )

            if input is not None:
                data = input.encode("utf-8") if isinstance(input, str) else input
                process.stdin.write(data)
                process.stdin.write_eof()
                await process.stdin.drain.aio()

            stdout = await process.stdout.read.aio()
            stderr = await process.stderr.read.aio()
            await process.wait.aio()

            return ExecResult(
                success=process.returncode == 0,
                returncode=process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )

        try:
            if timeout:
                result = await asyncio.wait_for(_run(), timeout=timeout)
            else:
                result = await _run()

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
                await self.sandbox.mkdir.aio(parent, parents=True)
            except Exception:
                pass  # Directory may already exist

        mode = "w" if isinstance(contents, str) else "wb"
        async with await self.sandbox.open.aio(file, mode) as f:
            await f.write.aio(contents)

    @override
    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        mode = "r" if text else "rb"

        try:
            async with await self.sandbox.open.aio(file, mode) as f:
                contents = await f.read.aio()
        except FileNotFoundError:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", file)
        except IsADirectoryError:
            raise IsADirectoryError(errno.EISDIR, "Is a directory", file)
        except modal.exception.FilesystemExecutionError:
            # Fallback for unspecified errors
            if await self._is_directory(file):
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

    async def _is_directory(self, path: str) -> bool:
        """Check if path is a directory."""
        try:
            process = await self.sandbox.exec.aio("test", "-d", path)
            await process.wait.aio()
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
