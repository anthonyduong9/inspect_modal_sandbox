from pathlib import Path
from typing import Callable

import pytest
from inspect_ai.util import parse_compose_yaml

from inspect_modal_sandbox._compose import convert_compose_to_modal_params

TmpComposeFixture = Callable[[str], Path]


@pytest.fixture
def tmp_compose(tmp_path: Path) -> Callable[[str], Path]:
    def create(contents: str) -> Path:
        compose_path = tmp_path / "compose.yaml"
        compose_path.write_text(contents)
        return compose_path

    return create


def test_converter_on_real_file(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11\nWORKDIR /app\n")

    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  my-service:
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /app
    environment:
      DEBUG: "true"
      API_KEY: secret
    mem_limit: 4g
    cpus: 2.0
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]
              count: 1
    x-inspect_modal_sandbox:
      timeout: 7200
      block_network: true
      cidr_allowlist:
        - "10.0.0.0/8"
        - "172.16.0.0/12"
""")
    config = parse_compose_yaml(str(compose_file))
    params = convert_compose_to_modal_params(config, str(compose_file))

    assert "image" in params
    assert params["workdir"] == "/app"
    assert params["env"] == {"DEBUG": "true", "API_KEY": "secret"}
    assert params["memory"] == 4096
    assert params["cpu"] == 2.0
    assert params["gpu"] == "1"
    assert params["timeout"] == 7200
    assert params["block_network"] is True
    assert params["cidr_allowlist"] == ["10.0.0.0/8", "172.16.0.0/12"]


### Service elements


def test_converts_image(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert "image" in params


def test_converts_build(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11\n")

    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  my-service:
    build:
      context: .
      dockerfile: Dockerfile
""")
    config = parse_compose_yaml(str(compose_file))
    params = convert_compose_to_modal_params(config, str(compose_file))

    assert "image" in params


def test_converts_working_dir(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["workdir"] == "/app"


def test_converts_environment_dict(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    environment:
      FOO: bar
      BAZ: qux
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["env"] == {"FOO": "bar", "BAZ": "qux"}


def test_converts_environment_list(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    environment:
      - FOO=bar
      - BAZ=qux
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["env"] == {"FOO": "bar", "BAZ": "qux"}


def test_converts_mem_limit(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    mem_limit: 2g
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["memory"] == 2048


def test_converts_cpus(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    cpus: 2.5
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["cpu"] == 2.5


def test_converts_deploy_gpu(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]
              count: 2
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["gpu"] == "2"


def test_converts_deploy_gpu_all(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]
              count: all
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["gpu"] == "all"


def test_converts_deploy_no_gpu(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert "gpu" not in params


@pytest.mark.parametrize(
    "value,expected",
    [
        ("512m", 512),
        ("512M", 512),
        ("512mb", 512),
        ("2g", 2048),
        ("2G", 2048),
        ("1gb", 1024),
        ("1.5g", 1536),
        ("0.5g", 512),
    ],
)
def test_can_convert_byte_value(
    value: str, expected: int, tmp_compose: TmpComposeFixture
) -> None:
    compose_path = tmp_compose(f"""
services:
  my-service:
    image: my-image
    mem_limit: {value}
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["memory"] == expected


### Extension elements


def test_converts_x_inspect_modal_sandbox(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    x-inspect_modal_sandbox:
      timeout: 3600
      cloud: aws
      region: us-east-1
      block_network: true
      cidr_allowlist:
        - "10.0.0.0/8"
      idle_timeout: 300
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["timeout"] == 3600
    assert params["cloud"] == "aws"
    assert params["region"] == "us-east-1"
    assert params["block_network"] is True
    assert params["cidr_allowlist"] == ["10.0.0.0/8"]
    assert params["idle_timeout"] == 300


def test_converts_x_inspect_modal_sandbox_partial(tmp_compose: TmpComposeFixture) -> None:  # noqa: E501
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
    x-inspect_modal_sandbox:
      block_network: true
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["block_network"] is True
    assert "timeout" not in params
    assert "cloud" not in params


def test_no_x_inspect_modal_sandbox(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  my-service:
    image: my-image
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert "block_network" not in params
    assert "timeout" not in params


### x-default handling


def test_keeps_service_named_default(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  other:
    image: other-image
  default:
    image: my-image
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["workdir"] == "/app"


def test_uses_service_with_x_default(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  other:
    image: other-image
  worker:
    image: my-image
    x-default: true
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["workdir"] == "/app"


def test_x_default_takes_precedence_over_service_named_default(
    tmp_compose: TmpComposeFixture,
) -> None:
    compose_path = tmp_compose("""
services:
  default:
    image: other-image
    working_dir: /other
  worker:
    image: my-image
    x-default: true
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["workdir"] == "/app"


def test_single_service_used_regardless_of_name(tmp_compose: TmpComposeFixture) -> None:
    compose_path = tmp_compose("""
services:
  myservice:
    image: my-image
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_path))
    params = convert_compose_to_modal_params(config, str(compose_path))

    assert params["workdir"] == "/app"
