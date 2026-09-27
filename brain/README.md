# nixin (PC brain)

Python package for the Nixin PC brain. See the [project README](../README.md) and [docs/SETUP.md](../docs/SETUP.md).

```bash
uv venv --python 3.12
uv pip install -e ".[voice,dev]"
cp .env.example .env         # add GROQ_API_KEY
nixin doctor                 # check keys, providers, audio, network
nixin demo                   # try with a simulated phone
nixin run                    # real phone: scan the QR with the Nixin app
pytest -q                    # tests (no network, no keys needed)
```

Commands: `run`, `demo`, `sim --pair <link>`, `doctor`, `models`, `send "<command>"`, `init`, `keys set <provider>`, `devices`, `unpair <id>`.
