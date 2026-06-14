# Contributing to Hermes GUI Automation

## Development Setup

```bash
git clone https://github.com/ScuraUrsa/hermes-gui-automation.git
cd hermes-gui-automation

python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Code Quality Standards

### Python
- All code must pass `ruff`, `mypy --strict`, and `bandit` with zero errors
- Type hints required on all function signatures
- Docstrings required on all public functions
- Tests must be self-contained and idempotent

### Ansible
- All playbooks must pass `ansible-playbook --syntax-check`
- All files must pass `ansible-lint` with zero errors
- All YAML must pass `yamllint`
- Roles must be idempotent

## Testing

```bash
pytest -m "not slow and not vlm"  # Fast tests
pytest -m app                      # Application integration tests
pytest -m vlm                      # VLM tests (requires models)
pytest                             # Full suite
```

## Architecture Decisions

All major architectural decisions are documented as ADRs in `GUI_AUTOMATION_REPORT.md`.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
