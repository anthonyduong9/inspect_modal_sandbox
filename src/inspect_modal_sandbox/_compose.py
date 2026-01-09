import re
from pathlib import Path
from typing import Any

import modal
from inspect_ai.util import ComposeConfig, ComposeService

SUPPORTED_FIELDS = [
    "image",
    "build",
    "working_dir",
    "environment",
    "mem_limit",
    "cpus",
    "deploy",  # For native GPU support via deploy.resources.reservations.devices
    "x-default",
    "x-inspect_modal_sandbox",
]


def _convert_byte_value(mem_limit: str) -> int:
    mem_limit = mem_limit.lower().strip()
    if not (match := re.match(r"^(\d+(?:\.\d+)?)\s*([kmgt]?)b?$", mem_limit)):
        raise ValueError(f"Invalid memory format: {mem_limit}")

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {"": 1, "k": 1 / 1024, "m": 1, "g": 1024, "t": 1024 * 1024}
    return int(value * multipliers[unit])


def _service_to_gpu(service: ComposeService) -> str | None:
    if not service.deploy or not service.deploy.resources:
        return None

    reservations = service.deploy.resources.reservations
    if not reservations or not reservations.devices:
        return None

    device = next((d for d in reservations.devices if d.capabilities and "gpu" in d.capabilities), None)  # noqa: E501
    if not device:
        return None

    if device.count:
        return str(device.count)
    if device.device_ids:
        return ",".join(device.device_ids)
    return "any"


def convert_compose_to_modal_params(
    config: ComposeConfig, compose_path: str
) -> dict[str, Any]:
    """Convert a ComposeConfig to Modal Sandbox.create() parameters.

    Args:
        config: Parsed compose configuration.
        compose_path: Path to the compose file (for resolving relative paths).

    Returns:
        Dictionary of parameters for Modal Sandbox.create().
    """
    service = next((svc for svc in config.services.values() if svc.x_default), None)
    if service is None:
        service = config.services.get("default") or next(iter(config.services.values()))

    params: dict[str, Any] = {}
    compose_dir = Path(compose_path).parent

    if service.build:
        if isinstance(service.build, str):
            dockerfile_path = compose_dir / service.build / "Dockerfile"
        else:
            context = service.build.context or "."
            dockerfile = service.build.dockerfile or "Dockerfile"
            dockerfile_path = compose_dir / context / dockerfile
        params["image"] = modal.Image.from_dockerfile(dockerfile_path)
    elif service.image:
        params["image"] = modal.Image.from_registry(service.image)

    if service.working_dir:
        params["workdir"] = service.working_dir

    if service.environment:
        if isinstance(service.environment, list):
            params["env"] = dict(item.split("=", 1) for item in service.environment if "=" in item)  # noqa: E501
        else:
            params["env"] = {k: v for k, v in service.environment.items() if v is not None}  # noqa: E501

    if service.mem_limit:
        params["memory"] = _convert_byte_value(service.mem_limit)

    if service.cpus:
        params["cpu"] = service.cpus

    gpu = _service_to_gpu(service)
    if gpu:
        params["gpu"] = gpu

    extensions = service.extensions.get("x-inspect_modal_sandbox", {})

    if extensions.get("block_network") is not None:
        params["block_network"] = extensions["block_network"]

    if extensions.get("cidr_allowlist") is not None:
        params["cidr_allowlist"] = extensions["cidr_allowlist"]

    if extensions.get("timeout") is not None:
        params["timeout"] = extensions["timeout"]

    if extensions.get("cloud") is not None:
        params["cloud"] = extensions["cloud"]

    if extensions.get("region") is not None:
        params["region"] = extensions["region"]

    if extensions.get("idle_timeout") is not None:
        params["idle_timeout"] = extensions["idle_timeout"]

    return params
