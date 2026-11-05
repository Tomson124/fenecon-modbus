# AGENTS.md

## Project overview

`fenecon-modbus` is an asyncio Python library (published on PyPI) that reads
FENECON energy management systems (FEMS) via their **Modbus/TCP read
interface**. It is the device/protocol layer for a separate Home Assistant
integration.

- No Home Assistant code in this repository. Do not import `homeassistant`.
- Read-only. The FEMS write interface ("Modbus/TCP schreibend") is out of scope.
- All I/O is async (`pymodbus` `AsyncModbusTcpClient`). Never block the event loop.

## Layout

```
src/fenecon_modbus/
  registers.py   register map (single source of truth), decoding, request grouping
  models.py      FeneconData, FeneconDeviceInfo, State, GridMode
  client.py      FeneconModbusClient: connect/close/read_data/read_device_info
  exceptions.py  FeneconError > FeneconConnectionError > FeneconTimeoutError; FeneconInvalidResponseError
  __init__.py    public API (keep __all__ in sync)
  py.typed
tests/
  conftest.py        FakeFems (fake register space) and mocked pymodbus client
  test_registers.py  register map checked row by row against the FEMS protocol
  test_client.py     public API, error handling, reconnects
```

## Setup and commands

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
uv sync                          # install package and dev dependencies
uv run pytest                    # run tests (no device needed)
uv run mypy src tests            # strict type checking
uv run ruff check src tests      # lint
uv run ruff format src tests     # format
uv build                         # build sdist and wheel
```

Before finishing a change, all four checks must pass: pytest, mypy, ruff check,
and ruff format --check.

## Register definitions: the most important rule

Register addresses, data types, units, enum values and sign conventions must
come **only** from these sources. Never invent or guess registers.

1. Official documentation, Tabelle 2 "Modbus-Tabelle Komponente Sum":
   https://docs.fenecon.de/de/fems/fems-app/App_ModbusTCP_read_access.html#_modbus_tabelle
2. The full Modbus protocol downloaded from a FEMS (OpenEMS 2026.10.1): online
   monitoring → Einstellungen → Anlagenprofil → ctrlApiModbusTcp →
   "PROTOKOLL HERUNTERLADEN". It is mirrored row by row in `PROTOCOL` in
   `tests/test_registers.py`.

If a needed register is not in these sources, stop and ask for the source
instead of guessing.

Facts from these sources that the code relies on:

- Addresses are zero-based. Port 502 and unit ID 1 are the defaults. Reads use function code 03.
- No scaling factors are defined; values come in their unit (`%`, `W`, `var`, `Wh`, `s`).
- Multi-register values are big-endian, high word first.
- Undefined values decode to `None`:
  - uint16/enum16: `0xFFFF`
  - uint64: `0xFFFF_FFFF_FFFF_FFFF`
  - float32/float64: NaN
  - string16: all zero bytes
- Signs:
  - ESS power: negative = charging, positive = discharging.
  - Grid power: negative = feed-in, positive = consumption.
  - Production power: always positive.
- Only addresses listed in the protocol may be requested. `build_read_blocks`
  merges data points only across documented `RESERVED_REGISTERS`. `FakeFems`
  raises `KeyError` on any other address.

### Adding or changing a register

1. `registers.py`: add the `Register` to `REGISTERS` (or `DEVICE_INFO_REGISTERS`), ordered by address.
   - Set `unit` and `enum`.
   - Set `cumulated=True` for `Wh_Σ` / `sec_Σ` units.
   - Add no-data rows to `RESERVED_REGISTERS`.
2. `models.py`: add a field to `FeneconData` / `FeneconDeviceInfo`.
   - Same name as `Register.key`, same position (field order must match register order).
   - Add a docstring with address and documented name.
3. `tests/test_registers.py`: add the row to `PROTOCOL` (and to `CUMULATED` if applicable).
4. `tests/conftest.py`: add a sample value to `SAMPLE_VALUES` / `SAMPLE_DEVICE_INFO`.
5. `README.md`: update the register table.

## Code style

- Python 3.14 syntax (`type` aliases, `match`, `Self`).
- Full type hints; `mypy --strict` must pass.
- Ruff, line length 120.
- Frozen, slotted, keyword-only dataclasses for returned data.
- Code, docstrings, comments and README are in English.
- Keep it focused: no abstractions beyond what reading the documented registers needs.

## Client behavior to preserve

- Connections are opened lazily. After any communication error the client closes the socket and reconnects on the next read.
- pymodbus auto-reconnect is disabled (`reconnect_delay=0`, `retries=0`).
- Reads are serialized with an `asyncio.Lock`. Cancellation closes the connection.
- Map pymodbus errors to library exceptions; never let pymodbus exceptions escape:

  | pymodbus / Python error | Library exception |
  |---|---|
  | `ConnectionException`, `OSError` | `FeneconConnectionError` |
  | `ModbusIOException`, `TimeoutError` | `FeneconTimeoutError` |
  | Other `ModbusException`, error responses, bad data | `FeneconInvalidResponseError` |

## Testing instructions

- Tests never need a real device. They patch `fenecon_modbus.client.AsyncModbusTcpClient` via the `modbus_client` fixture, backed by `FakeFems`.
- `pytest-asyncio` runs in auto mode: write `async def test_...` without markers.
- Cover new behavior with tests:
  - decoding, including sign and undefined values
  - error paths
  - public API changes
- `tests/` is on `pythonpath`, so import helpers with `from conftest import ...`.

## Security considerations

- The FEMS Modbus interface has no authentication. Never add write requests (function codes 05/06/15/16).
- Do not commit real hosts or IP addresses beyond documentation examples such as `192.168.0.20`.
