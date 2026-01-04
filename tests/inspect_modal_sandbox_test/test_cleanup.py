import asyncio

import modal

from inspect_modal_sandbox._modal_sandbox_environment import ModalSandboxEnvironment


async def test_cleanup() -> None:
    existing_sandbox_ids = _read_sandbox_ids()

    envs, new_sandbox_id = await _create_environment(task_name="test_cleanup")

    sandbox_ids = _read_sandbox_ids()
    assert new_sandbox_id in sandbox_ids - existing_sandbox_ids

    await ModalSandboxEnvironment.sample_cleanup(
        task_name="test_cleanup",
        config=None,
        environments=envs,
        interrupted=False,
    )

    await asyncio.sleep(2)

    post_cleanup_sandbox_ids = _read_sandbox_ids()
    assert new_sandbox_id not in post_cleanup_sandbox_ids


async def test_cli_cleanup() -> None:
    _, new_sandbox_id = await _create_environment(task_name="test_cli_cleanup")

    await ModalSandboxEnvironment.cli_cleanup(id=None)

    post_cleanup_sandbox_ids = _read_sandbox_ids()
    assert new_sandbox_id not in post_cleanup_sandbox_ids


async def _create_environment(
    task_name: str,
) -> tuple[dict[str, ModalSandboxEnvironment], str]:
    envs = await ModalSandboxEnvironment.sample_init(
        task_name=task_name,
        config=None,
        metadata={},
    )
    sandbox = envs["default"].sandbox
    return envs, sandbox.object_id


def _read_sandbox_ids() -> set[str]:
    return {sb.object_id for sb in modal.Sandbox.list()}
