# Changelog

## 0.3.0 - 2026-01-21

- Accept any YAML file as compose config (enables `{instance_id}-compose.yaml` patterns)

## 0.2.0 - 2026-01-19

- Add Docker Compose file support with `x-inspect_modal_sandbox` extensions
- Add `config_files()` for automatic compose/Dockerfile discovery
- Increase default sandbox timeout to 24 hours

## 0.1.1 - 2025-01-05

- Fix blocking I/O in async methods using Modal's native async API
