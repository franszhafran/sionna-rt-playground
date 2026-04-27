---
name: sim-adjust
description: Adjust the factory simulation — factory layout, radio config, UE distribution, or gNB placement — then optionally re-run the simulation on the remote and update sim_report.md.
---

You are helping the user adjust the car factory 5G simulation.

**Context:**
- Local repo: `/Users/franszhafran/code/sionna-rt`
- Remote: `ssh ma012@lkc`, directory `/home/ma012/sionna-rt-playground` (same git hash — never rsync)
- Key files:
  - `factory_layout.py` — factory geometry (buildings, partition walls, doors, gNB/UE positions)
  - `config.json` — runtime radio config (frequency, tx/rx array, OFDM params, noise variance)
  - `factory_sim.py` — simulation engine (OFDM beamforming, QoS SLA check, writes sim_results.json)
  - `factory_viewer.py` — WebGL 3D viewer (roof toggle, UE→gNB line toggle)

**When the user invokes /sim-adjust, ask:**
1. What they want to change: layout (buildings/walls/doors/gNBs/UEs) or radio config (frequency/array/beamforming)?
2. Specific changes (exact values or goals like "add a gNB in the south-west corner").

**Then:**
- Edit the relevant file(s) locally.
- If layout changed: run `factory_layout.py` on remote to regenerate PLY/XML:
  ```
  ssh ma012@lkc "cd /home/ma012/sionna-rt-playground && git pull && source venv/bin/activate && python factory_layout.py"
  ```
- Ask whether to re-run the simulation:
  ```
  ssh ma012@lkc "cd /home/ma012/sionna-rt-playground && source venv/bin/activate && python factory_sim.py 2>&1 | tail -60"
  ```
- If sim results are new, update `sim_report.md` locally with updated SLA, SINR, throughput numbers.
- Summarize what changed and the new SLA pass rate.

**Constraints:**
- Never rsync to remote — git pull is the sync mechanism.
- Push local changes with `git push` before running on remote.
- The remote venv is at `~/sionna-rt-playground/venv/` — always `source venv/bin/activate`.
