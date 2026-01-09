import re
from pathlib import Path
from typing import Any

import modal
from inspect_ai.util import ComposeConfig, ComposeService

MODAL_SUPPORTED_COMPOSE_FIELDS = [
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


def _parse_memory(mem_limit: str) -> int:
    mem_limit = mem_limit.lower().strip()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([kmgt]?)b?$", mem_limit)
    if not match:
        raise ValueError(f"Invalid memory format: {mem_limit}")

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {"": 1, "k": 1 / 1024, "m": 1, "g": 1024, "t": 1024 * 1024}
    return int(value * multipliers.get(unit, 1))


def _get_gpu_from_compose(service: ComposeService) -> str | None:
    if not service.deploy or not service.deploy.resources:
        return None

    reservations = service.deploy.resources.reservations
    if not reservations or not reservations.devices:
        return None

    for device in reservations.devices:
        if device.capabilities and "gpu" in device.capabilities:
            # Return the count or device_ids if specified, else just "any"
            if device.count:
                return str(device.count)
            elif device.device_ids:
                return ",".join(device.device_ids)
            return "any"

    return None


def compose_to_modal_params(
    config: ComposeConfig, compose_path: str
) -> dict[str, Any]:
    """Convert a ComposeConfig to Modal Sandbox.create() parameters.

    Args:
        config: Parsed compose configuration.
        compose_path: Path to the compose file (for resolving relative paths).

    Returns:
        Dictionary of parameters for Modal Sandbox.create().
    """
    # Get the default service (first one, or one marked x-default)
    service: ComposeService | None = None
    for name, svc in config.services.items():
        if svc.x_default:
            service = svc
            break
    if service is None:
        # Use the first service, or "default" if it exists
        service = config.services.get("default") or next(iter(config.services.values()))

    params: dict[str, Any] = {}
    compose_dir = Path(compose_path).parent

    # Image handling
    if service.build:
        # Build from Dockerfile
        if isinstance(service.build, str):
            dockerfile_path = compose_dir / service.build / "Dockerfile"
        else:
            context = service.build.context or "."
            dockerfile = service.build.dockerfile or "Dockerfile"
            dockerfile_path = compose_dir / context / dockerfile
        params["image"] = modal.Image.from_dockerfile(str(dockerfile_path))
    elif service.image:
        params["image"] = modal.Image.from_registry(service.image)

    # Working directory
    if service.working_dir:
        params["workdir"] = service.working_dir

    # Environment variables
    if service.environment:
        if isinstance(service.environment, list):
            # Convert ["KEY=value", ...] to {"KEY": "value", ...}
            env_dict = {}
            for item in service.environment:
                if "=" in item:
                    key, value = item.split("=", 1)
                    env_dict[key] = value
            params["env"] = env_dict
        else:
            # Filter out None values
            params["env"] = {k: v for k, v in service.environment.items() if v is not None}  # noqa: E501

    # Memory limit
    if service.mem_limit:
        params["memory"] = _parse_memory(service.mem_limit)

    # CPU
    if service.cpus:
        params["cpu"] = service.cpus

    gpu = _get_gpu_from_compose(service)
    if gpu:
        params["gpu"] = gpu

    # Modal-specific extensions under x-inspect_modal_sandbox namespace
    modal_ext = service.extensions.get("x-inspect_modal_sandbox", {})

    if modal_ext.get("block_network") is not None:
        params["block_network"] = modal_ext["block_network"]

    if modal_ext.get("cidr_allowlist") is not None:
        params["cidr_allowlist"] = modal_ext["cidr_allowlist"]

    if modal_ext.get("timeout") is not None:
        params["timeout"] = modal_ext["timeout"]

    if modal_ext.get("cloud") is not None:
        params["cloud"] = modal_ext["cloud"]

    if modal_ext.get("region") is not None:
        params["region"] = modal_ext["region"]

    if modal_ext.get("idle_timeout") is not None:
        params["idle_timeout"] = modal_ext["idle_timeout"]

    return params
