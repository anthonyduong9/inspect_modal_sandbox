"""Tests for Docker Compose to Modal parameter conversion."""

import pytest
from inspect_ai.util import parse_compose_yaml

from inspect_modal_sandbox._compose import compose_to_modal_params


def test_converter_on_real_file(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11\nWORKDIR /app\n")

    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
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
    params = compose_to_modal_params(config, str(compose_file))

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


def test_converts_image(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert "image" in params


def test_converts_build(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11\n")

    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    build:
      context: .
      dockerfile: Dockerfile
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert "image" in params


def test_converts_working_dir(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["workdir"] == "/app"


def test_converts_environment_dict(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    environment:
      FOO: bar
      BAZ: qux
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["env"] == {"FOO": "bar", "BAZ": "qux"}


def test_converts_environment_list(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    environment:
      - FOO=bar
      - BAZ=qux
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["env"] == {"FOO": "bar", "BAZ": "qux"}


def test_converts_mem_limit(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    mem_limit: 2g
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["memory"] == 2048


def test_converts_cpus(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    cpus: 2.5
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["cpu"] == 2.5


def test_converts_deploy_gpu(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]
              count: 2
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["gpu"] == "2"


def test_converts_deploy_gpu_all(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              capabilities: [gpu]
              count: all
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["gpu"] == "all"


def test_converts_deploy_no_gpu(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

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
def test_can_convert_byte_value(value: str, expected: int, tmp_path) -> None:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text(f"""
services:
  default:
    image: python:3.11
    mem_limit: {value}
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["memory"] == expected


### Extension elements


def test_converts_x_inspect_modal_sandbox(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    x-inspect_modal_sandbox:
      timeout: 3600
      cloud: aws
      region: us-east-1
      block_network: true
      cidr_allowlist:
        - "10.0.0.0/8"
      idle_timeout: 300
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["timeout"] == 3600
    assert params["cloud"] == "aws"
    assert params["region"] == "us-east-1"
    assert params["block_network"] is True
    assert params["cidr_allowlist"] == ["10.0.0.0/8"]
    assert params["idle_timeout"] == 300


def test_converts_x_inspect_modal_sandbox_partial(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
    x-inspect_modal_sandbox:
      block_network: true
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["block_network"] is True
    assert "timeout" not in params
    assert "cloud" not in params


def test_no_x_inspect_modal_sandbox(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: python:3.11
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert "block_network" not in params
    assert "timeout" not in params


### x-default handling


def test_keeps_service_named_default(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  other:
    image: nginx
  default:
    image: python:3.11
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["workdir"] == "/app"


def test_uses_service_with_x_default(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  web:
    image: nginx
  worker:
    image: python:3.11
    x-default: true
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["workdir"] == "/app"


def test_x_default_takes_precedence_over_service_named_default(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: nginx
    working_dir: /nginx
  worker:
    image: python:3.11
    x-default: true
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["workdir"] == "/app"


def test_single_service_used_regardless_of_name(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  myservice:
    image: python:3.11
    working_dir: /app
""")
    config = parse_compose_yaml(str(compose_file))
    params = compose_to_modal_params(config, str(compose_file))

    assert params["workdir"] == "/app"
