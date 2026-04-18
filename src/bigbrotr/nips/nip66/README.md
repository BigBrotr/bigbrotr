# nip66

NIP-66 relay monitoring checks and typed outputs.

## Main Files

- `nip66.py`: orchestration entrypoint for the NIP-66 family.
- `rtt.py`, `ssl.py`, `geo.py`, `net.py`, `dns.py`, `http.py`: individual check
  implementations.
- `data.py`, `logs.py`: structured check payloads and logs.

## Rules

- Each check module should stay focused on one probe family.
- Cross-check orchestration belongs in `nip66.py`, not in the individual probe
  modules.
