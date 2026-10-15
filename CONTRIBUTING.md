# Contributing to mktsim

Thanks for helping out. Keep it simple: small, tested, documented changes.

## Setup

```powershell
git clone https://github.com/ASH-SuperUser/mktsim.git
cd mktsim
py -m venv venv
.\venv\Scripts\python.exe -m pip install -e ".[gui,test]"
```

Always use the project venv — nothing global.

## Workflow

1. Change code under `src/mktsim/`.
2. Add or update tests under `tests/` (`pytest -q` must stay green).
3. If simulator behaviour changed, regenerate the examples page:
   `.\venv\Scripts\python.exe docs/gen_examples.py`.
4. Verify the docs build: `.\venv\Scripts\mkdocs.exe build --strict`.
5. Keep `CHANGELOG.md` updated (newest entry on top).

## Conventions

- Core simulators stay **stdlib-only** — new hard dependencies need a
  strong reason and an entry in `pyproject.toml`.
- Everything public is type-annotated and takes `seed` where randomness
  is involved.
- New simulator submodules are picked up automatically by the CLI/GUI
  discovery — no registration step needed.

## Release checklist

Release notes live in the local `tmp/publishing.md`. In short: sync
`pyproject.toml` version with `mktsim.__version__`, run the suite,
`python -m build`, `twine check dist/*`, upload.
