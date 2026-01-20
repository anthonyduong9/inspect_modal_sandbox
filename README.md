# Inspect Modal Sandbox

## Purpose

This plugin for [Inspect](https://inspect.aisi.org.uk/) allows you to use containers
as sandboxes, running within [Modal](https://modal.com/).

## Installing

Add this using [Poetry](https://python-poetry.org/)

```
poetry add git+ssh://git@github.com/anthonyduong9/inspect_modal_sandbox.git
```

or in [uv](https://github.com/astral-sh/uv),

```
uv add git+ssh://git@github.com/anthonyduong9/inspect_modal_sandbox.git
```

## Requirements

This plugin requires a Modal account. Sign up at [modal.com](https://modal.com/).

Authenticate the Modal CLI:

```bash
pip install modal
python3 -m modal setup
```

## Configuring evals

You can configure the eval using either a Docker Compose file, or by specifying a Dockerfile path.

By default, the provider uses Modal's default Debian-based image with Python 3.11.

### Docker Compose

The `services` key is required. All other options are optional.

```yaml
services:
  default:
    image: python:3.12
    build:
      context: .
      dockerfile: Dockerfile
    working_dir: /app
    environment:
      MY_VAR: "value"
    mem_limit: 1g
    cpus: 2.0
x-inspect_modal_sandbox:
  timeout: 3600
  idle_timeout: 300
  block_network: false
  cidr_allowlist:
    - "0.0.0.0/0"
  cloud: aws
  region: us-east-1
```

### Dockerfile

As an alternative to Docker Compose you can specify a Dockerfile path directly, e.g.

```python
sandbox=("modal", "path/to/Dockerfile")
```

## Known Limitations

- **User switching**: The `user` parameter in `exec()` is ignored. Commands run as the container's default user (root).
- **Root execution**: Modal containers run as root by default.

## Developing

See [CONTRIBUTING.md](CONTRIBUTING.md)
