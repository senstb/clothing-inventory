# Contributing

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Notes
- Keep changes small and test-driven where possible.
- Update tests when behavior changes.
- Avoid committing local database files or uploaded images.
