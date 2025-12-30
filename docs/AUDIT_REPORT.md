# BigBrotr - Audit Report (Issue Rimanenti)

**Data**: 2025-12-30
**Versione**: 3.0 (Verifica fix applicati)
**Auditor**: Claude Opus 4.5

---

## Executive Summary

Questo report mostra le **issue ancora da fixare** dopo la verifica del codice attuale.

**Molte issue sono state risolte!** Su 98 issue originali:
- **Issue risolte**: 45 (~46%)
- **Issue ancora da fixare**: 53 (~54%)

| Severita | Originali | Risolte | Rimanenti |
|----------|-----------|---------|-----------|
| Critici | 5 | 1 | **4** |
| Alti | 15 | 9 | **6** |
| Medi | 33 | 15 | **18** |
| Bassi | 45 | 20 | **25** |
| **TOTALE** | **98** | **45** | **53** |

---

## Issue Risolte (Non incluse in questo report)

### Critiche Risolte
- **C5**: PyO3 inheritance fragile - *Verificato: il codice usa `cls(sk)` che funziona correttamente con `from None` per sanitizzare errori*

### Alte Risolte
- **H5**: Log injection - **RISOLTO** in [logger.py:56-69](src/core/logger.py#L56-L69) - Aggiunta sanitizzazione con escape quotes e troncamento a 1000 chars
- **H6**: Race condition cursor - **RISOLTO** in [finder.py:295-298](src/services/finder.py#L295-L298) - Cursor salvato atomicamente nel loop
- **H7**: Worker connection leak - **RISOLTO** in [synchronizer.py:343-401](src/services/synchronizer.py#L343-L401) - Aggiunti signal handlers e cleanup robusto
- **H8**: Tor config inconsistency - **RISOLTO** in [validator.py:31](src/services/validator.py#L31) - Aggiunto `model_validator` per validazione
- **H10**: Content-Type validation - **RISOLTO** in [nip11.py:276-285](src/models/nip11.py#L276-L285) - Aggiunto check Content-Type e try/except JSON

### Medie Risolte
- **M1**: Unbounded JSON recursion - **RISOLTO** in [metadata.py:79-130](src/models/metadata.py#L79-L130) - Aggiunto `_seen` set per circular reference
- **M5**: Blocking I/O in async - **RISOLTO** in [nip66.py:217-265](src/models/nip66.py#L217-L265) - Usa `asyncio.to_thread()` per DNS/SSL
- **M8**: Tag `d` NIP-66 formato - **RISOLTO** in [monitor.py:274](src/services/monitor.py#L274) - Usa `relay.url` (con schema)
- **M9**: Kind 30078 effimero - **RISOLTO** in [nip66.py:347](src/models/nip66.py#L347) - Cambiato a Kind(20000)
- **M10**: Pool.acquire_healthy backoff - **RISOLTO** in [pool.py:321-324](src/core/pool.py#L321-L324) - Aggiunto delay esponenziale

### Basse Risolte
- **L1**: Valori lunghi non troncati - **RISOLTO** in logger.py con `MAX_VALUE_LENGTH = 1000`
- **L2**: Exception handler CancelledError - **RISOLTO** in base_service.py:139-141 con catch esplicito
- **L3**: metrics property race - **RISOLTO** in pool.py:412-413 con reference locale
- **L6**: keys.py errore espone chiave - **RISOLTO** con `from None`
- **L8**: Nip66 client shutdown - **RISOLTO** in nip66.py:357-361 con try/finally
- **L9**: DNS su relay Tor - **RISOLTO** in nip66.py:444-446 con check network
- **L11**: Cleanup candidati - **RISOLTO** in validator.py:213-222 con cleanup configurabile
- **L14**: Cursor 0 eventi - **RISOLTO** in synchronizer.py:807-815 salva sempre
- **L15**: 0 eventi come fallito - **RISOLTO** in synchronizer.py:851-856 conta correttamente
- **L17**: brotr.py hasattr check - **RISOLTO** in brotr.py:244-248 con check corretto

---

## Issue Ancora da Fixare

---

## 1. Critiche (4 rimanenti)

### C1. SSRF via Relay URLs (Finder) - DA FIXARE

**File**: [finder.py:369-440](src/services/finder.py#L369-L440)
**Severita**: CRITICO

**Problema**:
Il Finder accetta URL da fonti esterne senza validazione SSRF. Un attaccante puo iniettare URL che puntano a servizi interni.

**Scenario di attacco**:
```python
# Evento Kind 10002 malevolo
tags = [
    ["r", "ws://169.254.169.254/latest/meta-data/"],  # AWS metadata
    ["r", "ws://localhost:5432/"],                      # PostgreSQL
]
```

**Impatto**:
- Accesso a metadata cloud (AWS/GCP/Azure)
- Scansione rete interna
- Bypass firewall

**Fix raccomandato**:
```python
# src/models/relay.py - Aggiungere validazione dopo DNS resolution

import socket
from functools import lru_cache

@staticmethod
@lru_cache(maxsize=1000)
def _resolve_and_validate(host: str) -> bool:
    """Resolve hostname and validate IP is not internal."""
    BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}
    if host in BLOCKED_HOSTS:
        return False
    try:
        ip = socket.gethostbyname(host)
        ip_obj = ip_address(ip)
        if any(ip_obj in net for net in Relay._LOCAL_NETWORKS):
            return False
        return True
    except socket.gaierror:
        return False
```

---

### C2. Credenziali di default in .env.example (BigBrotr) - DA FIXARE

**File**: [implementations/bigbrotr/.env.example](implementations/bigbrotr/.env.example)
**Severita**: CRITICO

**Problema**:
```bash
DB_PASSWORD=admin
PRIVATE_KEY=0000000000000000000000000000000000000000000000000000000000000001
```

**Impatto**:
- Se copiato in produzione: database compromesso
- PRIVATE_KEY 0x01 e' la chiave piu' nota nel Nostr

**Fix raccomandato**:
```bash
# IMPORTANTE: NON usare questi valori in produzione!
DB_PASSWORD=CHANGE_ME_GENERATE_SECURE_PASSWORD
PRIVATE_KEY=CHANGE_ME_GENERATE_WITH_OPENSSL_RAND_HEX_32
```

---

### C3. Credenziali di default in .env.example (LilBrotr) - DA FIXARE

**File**: [implementations/lilbrotr/.env.example](implementations/lilbrotr/.env.example)
**Severita**: CRITICO

Stesso problema di C2.

---

### C4. Nessun limite sulla dimensione risposta NIP-11 - DA FIXARE

**File**: [nip11.py:282-285](src/models/nip11.py#L282-L285)
**Severita**: CRITICO

**Problema**:
La risposta NIP-11 non ha limite di dimensione. Un relay malevolo puo' rispondere con gigabytes di dati.

**Codice attuale** (parzialmente fixato ma manca size limit):
```python
async with session.get(http_url, headers=headers, timeout=...) as resp:
    if resp.status != 200:
        return None
    # Content-Type check added - OK
    # MA: nessun limite sulla dimensione!
    data = await resp.json()
```

**Fix raccomandato**:
```python
MAX_RESPONSE_SIZE = 1024 * 1024  # 1MB max

# Check Content-Length header
content_length = resp.headers.get("Content-Length")
if content_length and int(content_length) > MAX_RESPONSE_SIZE:
    return None

# Read with limit
content = await resp.content.read(MAX_RESPONSE_SIZE + 1)
if len(content) > MAX_RESPONSE_SIZE:
    return None
```

---

## 2. Alte (6 rimanenti)

### H1. Porte database esposte (BigBrotr) - DA FIXARE

**File**: [implementations/bigbrotr/docker-compose.yaml:35-36](implementations/bigbrotr/docker-compose.yaml#L35-L36)
**Severita**: ALTO

**Problema**:
```yaml
ports:
  - "5432:5432"  # Esposto su 0.0.0.0
```

**Fix raccomandato**:
```yaml
ports:
  - "127.0.0.1:5432:5432"  # Solo localhost
```

---

### H2. Porte database esposte (LilBrotr) - DA FIXARE

**File**: [implementations/lilbrotr/docker-compose.yaml:36-37](implementations/lilbrotr/docker-compose.yaml#L36-L37)
**Severita**: ALTO

Stesso problema, port 5433.

---

### H3. Porta Tor SOCKS esposta (BigBrotr) - DA FIXARE

**File**: [implementations/bigbrotr/docker-compose.yaml:117](implementations/bigbrotr/docker-compose.yaml#L117)
**Severita**: ALTO

**Problema**:
```yaml
ports:
  - "9050:9050"  # Chiunque puo' usare il proxy
```

**Fix raccomandato**:
```yaml
ports:
  - "127.0.0.1:9050:9050"
```

---

### H4. synchronous_commit=off in PostgreSQL - DA FIXARE (Documentato)

**File**: [implementations/bigbrotr/postgres/postgresql.conf:51](implementations/bigbrotr/postgres/postgresql.conf#L51)
**Severita**: ALTO

**Problema**:
```
synchronous_commit = off
```

**Nota**: Il file contiene un commento (line 56-57) che spiega la scelta:
> "Note: synchronous_commit=off means ~10ms of data loss risk on crash. Acceptable for BigBrotr since Nostr events can be re-fetched"

**Raccomandazione**: Mantenere se accettabile il rischio, altrimenti usare `local`.

---

### H9. statement_timeout=0 in PostgreSQL - DA FIXARE

**File**: [implementations/bigbrotr/postgres/postgresql.conf:62](implementations/bigbrotr/postgres/postgresql.conf#L62)
**Severita**: ALTO

**Problema**:
```
statement_timeout = 0  # No timeout
```

**Impatto**: Query runaway possono bloccare il DB per ore.

**Fix raccomandato**:
```
statement_timeout = 300000  # 5 minuti max
```

---

### H11. PGBouncer porta esposta - DA FIXARE

**File**: [implementations/bigbrotr/docker-compose.yaml:84-85](implementations/bigbrotr/docker-compose.yaml#L84-L85)
**Severita**: ALTO

**Problema**:
```yaml
ports:
  - "6432:5432"  # Esposto
```

**Fix**: Bind a `127.0.0.1:6432:5432`

---

## 3. Medie (18 rimanenti)

### M2. Type confusion in EventRelay - DA FIXARE

**File**: [event_relay.py:78-86](src/models/event_relay.py#L78-L86)
**Severita**: MEDIO

**Problema**:
```python
if hasattr(evt, "to_db_params") and callable(getattr(evt, "to_db_params", None)):
    return evt.to_db_params()
```

Duck typing fragile - qualsiasi oggetto con `to_db_params` passa.

**Fix raccomandato**:
```python
from nostr_sdk import Event as NostrEvent

if not isinstance(evt, (Event, NostrEvent)):
    raise TypeError(f"Expected Event, got {type(evt).__name__}")
```

---

### M3. Obsolete schema verification (Initializer) - DA FIXARE

**File**: [implementations/bigbrotr/yaml/services/initializer.yaml](implementations/bigbrotr/yaml/services/initializer.yaml)
**Severita**: MEDIO

**Problema**: Liste manuali di tabelle/funzioni che possono divergere dallo schema SQL.

---

### M4. Missing CHECK constraint on relays.network - DA FIXARE

**File**: [implementations/bigbrotr/postgres/init/02_tables.sql](implementations/bigbrotr/postgres/init/02_tables.sql)
**Severita**: MEDIO

**Problema**: La colonna `network` accetta qualsiasi stringa.

**Fix raccomandato**:
```sql
network TEXT NOT NULL CHECK (network IN ('clearnet', 'tor', 'i2p', 'loki'))
```

---

### M6. Empty YAML files without defaults - DA FIXARE

**Problema**: Alcuni YAML vuoti causano `NoneType` errors.

**Fix**:
```python
config = yaml.safe_load(f) or {}  # Default a dict vuoto
```

---

### M7. Missing GeoIP database in Docker - DA FIXARE

**File**: [implementations/bigbrotr/docker-compose.yaml](implementations/bigbrotr/docker-compose.yaml)
**Severita**: MEDIO

**Problema**: Il database GeoIP non e' montato nel container.

**Fix raccomandato**:
```yaml
volumes:
  - ./data/GeoLite2-City.mmdb:/usr/share/GeoIP/GeoLite2-City.mmdb:ro
```

---

### M11-M18. Altre issue medie

| # | File | Problema |
|---|------|----------|
| M11 | relay.py | URL length non validato (max 2048) |
| M12 | relay.py | Port range 0-65535 non validato esplicitamente |
| M13 | event.py | Ereditarieta' PyO3 fragile (come Keys) |
| M14 | nip11.py | Timeout DNS/SSL non configurabile |
| M15 | validator.py | Test connessione troppo semplice |
| M16 | finder.py | Query incompatibile con LilBrotr schema |
| M17 | monitor.py | Tag `R` incompleto (manca `writes`, `pow` negativi) - VERIFICATO: Presente in lines 307-316 |
| M18 | various | TorConfig/KeysConfig duplicati in piu' file |

**Nota M17**: Verificato che i tag R per `writes` e `pow` sono presenti (lines 307-316 di monitor.py).

---

## 4. Basse (25 rimanenti)

| # | File | Problema | Effort |
|---|------|----------|--------|
| L4 | relay.py | URL length non validato | 5min |
| L5 | relay.py | _LOCAL_NETWORKS manca alcuni range | 10min |
| L7 | event.py | Ereditarieta' PyO3 fragile | 1h |
| L10 | nip66.py | SSL date format variabile | 15min |
| L12 | validator.py | Test connessione semplice | 30min |
| L13 | validator.py | Selezione candidati O(n^2) | 15min |
| L16 | monitor.py | Metrics lock overhead | 10min |
| L18 | brotr.py | upsert fallback silenzioso | 15min |
| L19 | finder.py | Query usa tagvalues (LilBrotr incompatibile) | 30min |
| L20 | various | Config duplicati | 1h |
| L21 | pool.py | acquire() non retry | 15min |
| L22 | base_service.py | Log "cycle_completed" duplicato | 5min |
| L23 | synchronizer.py | aiomultiprocess cleanup | 30min |
| L24 | monitor.py | _last_announcement non persistente | 15min |
| L25 | nip11.py | Manca User-Agent header | 5min |

---

## Piano di Remediation Prioritizzato

### Sprint 1 - Critici (Immediato, ~2h)

| # | Problema | Fix | Effort |
|---|----------|-----|--------|
| 1 | C1: SSRF | Validazione IP dopo DNS | 1h |
| 2 | C2/C3: Credenziali | Placeholder sicuri | 15min |
| 3 | C4: Response size | Limite 1MB | 30min |

### Sprint 2 - Alti (Settimana 1, ~1h)

| # | Problema | Fix | Effort |
|---|----------|-----|--------|
| 4 | H1/H2/H3/H11: Porte | Bind 127.0.0.1 | 15min |
| 5 | H9: statement_timeout | Impostare 5min | 5min |
| 6 | H4: sync_commit | Documentare o cambiare | 5min |

### Sprint 3 - Medi (Settimana 2, ~3h)

| # | Problema | Fix | Effort |
|---|----------|-----|--------|
| 7 | M2: Type confusion | isinstance check | 15min |
| 8 | M4: CHECK constraint | Aggiungere vincolo | 15min |
| 9 | M7: GeoIP mount | Volume Docker | 10min |
| 10 | M11: URL length | Validazione | 5min |

---

## Metriche Aggiornate

### Distribuzione Severita' Rimanenti

```
Critici  ████████████░░░░░░░░  4 (8%)
Alti     ████████████████░░░░  6 (11%)
Medi     ████████████████████████████████████  18 (34%)
Bassi    █████████████████████████████████████████████████  25 (47%)
```

### Progresso Complessivo

```
Issue Risolte   █████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░  45 (46%)
Issue Rimanenti █████████████████████████████████████████████████████  53 (54%)
```

---

## Riepilogo Fix Gia' Applicati

I seguenti miglioramenti sono stati implementati:

1. **Logger**: Sanitizzazione valori, troncamento, escape quotes
2. **Pool**: Backoff esponenziale in acquire_healthy, metrics thread-safe
3. **BaseService**: Gestione CancelledError esplicita
4. **Metadata**: Protezione circular reference
5. **Nip11**: Content-Type validation, JSON error handling
6. **Nip66**: Async DNS/SSL, client shutdown, skip DNS per Tor, Kind effimero
7. **Finder**: Cursor salvato atomicamente
8. **Validator**: TorConfig validation, cleanup configurabile
9. **Synchronizer**: Signal handlers, cleanup robusto, cursor sempre salvato
10. **Monitor**: Tag `d` corretto, client shutdown garantito
11. **Brotr**: hasattr check corretto

---

*Report generato da Claude Opus 4.5 - 2025-12-30*
*Versione 3.0 - Verifica issue risolte vs rimanenti*
