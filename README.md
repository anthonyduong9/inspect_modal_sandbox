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

## Container Image

By default, the provider uses Modal's default Debian-based image with Python 3.11.

You can specify a custom Dockerfile:

```python
sandbox=("modal", "path/to/Dockerfile")
```

## Configuring evals

Basic usage:

```python
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate

@task
def my_task():
    return Task(
        dataset=[Sample(input="Hello")],
        solver=generate(),
        sandbox="modal",
    )
```

With a custom Dockerfile:

```python
@task
def my_task():
    return Task(
        dataset=[...],
        solver=generate(),
        sandbox=("modal", "path/to/Dockerfile"),
    )
```

From command line:

```bash
inspect eval my_task.py --sandbox modal
inspect eval my_task.py --sandbox modal:path/to/Dockerfile
```

## Known Limitations

- **User switching**: The `user` parameter in `exec()` is ignored. Commands run as the container's default user (root).
- **Network access**: Modal sandboxes have internet access by default. See [Modal's networking docs](https://modal.com/docs/guide/sandbox-networking) for restrictions
- **Root execution**: Modal containers run as root by default

## Tech Debt / Missing features

- CLI cleanup command not implemented
- Configuration options (timeout, resources) not yet exposed

## Developing

See [CONTRIBUTING.md](CONTRIBUTING.md)
