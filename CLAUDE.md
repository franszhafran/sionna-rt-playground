# CLAUDE.md — Project Instructions

## Remote

- Remote host: `ssh ma012@lkc`
- Remote directory: `/home/ma012/sionna-rt-playground`
- Python venv: `source venv/bin/activate` (always activate before running any Python)
- **Never rsync** — the remote and local repos share the same git history

## Workflow for making changes

- Edit files **locally** (factory_layout.py, factory_sim.py, factory_viewer.py, config.json, etc.)
- Commit and push: `git add <files> && git commit -m "..." && git push origin main`
- On remote, pull the changes: `ssh ma012@lkc "cd /home/ma012/sionna-rt-playground && git pull"`
- If the remote has uncommitted local edits, stash first: `git stash && git pull`

## Where to run things

- **Scene generation** (`factory_layout.py`) — run on **remote**
  ```
  ssh ma012@lkc "cd /home/ma012/sionna-rt-playground && source venv/bin/activate && python factory_layout.py"
  ```
- **Simulation** (`factory_sim.py`) — run on **remote** (GPU/Sionna RT required)
  ```
  ssh ma012@lkc "cd /home/ma012/sionna-rt-playground && source venv/bin/activate && python factory_sim.py 2>&1"
  ```
- **3D viewer** (`factory_viewer.py`) — run **locally** (serves browser on localhost:8889)
  ```
  python factory_viewer.py
  ```

## After simulation

- Copy `sim_results.json` back to local: `scp ma012@lkc:/home/ma012/sionna-rt-playground/sim_results.json .`
- Update `sim_report.md` with new SLA, SINR, and throughput numbers from the remote output

## Key files

- `factory_layout.py` — factory geometry: buildings, internal partition walls, doors, gNB/UE positions
- `factory_sim.py` — OFDM ray-tracing simulation: CFR, MMSE beamforming, QoS SLA check; writes `sim_results.json`
- `factory_viewer.py` — Three.js WebGL viewer: roof toggle, UE→gNB connection lines toggle
- `config.json` — runtime radio config: frequency, array size, beamforming method, noise variance
- `sim_results.json` — output of last sim run (best_gnb per UE, throughput, SINR, SLA pass flags)
- `sim_report.md` — human-readable report; update manually after each sim run

## Slash commands

- `/sim-adjust` — guided flow for adjusting layout or radio config, with remote re-run prompt
