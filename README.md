# fenecon-modbus

Asynchronous Python client for FENECON energy management systems (FEMS) via
the **Modbus/TCP read interface**. It is a pure device/protocol library built
on `asyncio` and [`pymodbus`](https://github.com/pymodbus-dev/pymodbus), intended
as the backend of a Home Assistant integration. It contains no Home Assistant code.

The register map follows these sources exactly:

- the official documentation
  [FEMS App Modbus/TCP lesend – Modbus-Tabelle](https://docs.fenecon.de/de/fems/fems-app/App_ModbusTCP_read_access.html#_modbus_tabelle)
  (Tabelle 2, component `_sum`), and
- the complete Modbus protocol of a FEMS running OpenEMS 2026.10.1 (online
  monitoring → *Einstellungen* → *Anlagenprofil* → `ctrlApiModbusTcp` →
  *PROTOKOLL HERUNTERLADEN*). It adds the `_meta` header, the per-phase values,
  `GridModeOffGridTime`, `EssCapacity`, the sign conventions and the encoding of
  undefined values.

## Prerequisites on the FEMS

- The app **"FEMS App Modbus/TCP lesend"** (`ctrlApiModbusTcp`) must be active
  on the FEMS. According to the Fenecon documentation the read interface is
  included and preinstalled from the factory. You can check it in the online
  monitoring under *Einstellungen → Anlagenprofil*.
- The machine running this library needs direct network access to the FEMS IP
  address (for example the same local network).
- Fenecon's defaults are port `502` and unit ID `1`. Both are configurable, as is the host.

## Installation

```bash
pip install fenecon-modbus
```

## Usage

```python
import asyncio

from fenecon_modbus import FeneconConnectionError, FeneconModbusClient


async def main() -> None:
    async with FeneconModbusClient("192.168.0.20", port=502) as client:
        try:
            info = await client.read_device_info()  # once, e.g. during setup
            data = await client.read_data()  # on every poll
        except FeneconConnectionError as err:  # includes FeneconTimeoutError
            print(f"FEMS not reachable: {err}")
            return
        print(f"{info.manufacturer} {info.manufacturer_model} {info.manufacturer_ems_serial_number}")
        print(f"OpenEMS {info.openems_version}")
        print(f"SoC: {data.ess_soc} %")
        print(f"Grid: {data.grid_active_power} W")
        print(f"PV: {data.production_active_power} W")
        print(f"Grid buy/sell: {data.grid_buy_active_energy} / {data.grid_sell_active_energy} Wh")


asyncio.run(main())
```

`read_data()` connects on demand. After a dropped connection or a timeout, it
closes the socket and reconnects on the next call, which suits a polling
coordinator. Concurrent calls are serialized.

### Device info

`read_device_info()` returns a `FeneconDeviceInfo` with the identification data
of the `_meta` header: the OpenEMS version (`openems_version_major/minor/patch`
and the `openems_version` property, e.g. `"2026.10.1"`), `manufacturer`,
`manufacturer_model`, `manufacturer_options`, `manufacturer_version`,
`manufacturer_serial_number` and `manufacturer_ems_serial_number`. It also
checks register 0 for the OpenEMS identifier `0x6201` and raises
`FeneconInvalidResponseError` if the server is not an OpenEMS Modbus/TCP API.
This is useful when validating a host in a config flow.

### Data

`FeneconData` is a frozen dataclass with one field per register. Values come in
the documented unit (`%`, `W`, `var`, `Wh`, `s`); no scaling factors are defined.
A field is `None` if the FEMS reports the value as undefined (uint16/enum16
`0xFFFF`, uint64 `0xFFFFFFFFFFFFFFFF`, NaN for floats, an all-zero string), if an
enum value is unknown, or if the SoC is outside 0–100.

Sign conventions, as stated in the protocol:

- ESS power (`ess_active_power*`, `ess_discharge_power`): negative = charging, positive = discharging.
- Grid power (`grid_active_power*`): negative = feed-in (sell), positive = consumption (buy).
- Production power: always positive.

Address, documented name, data type and unit of every field are available as
metadata, for example to build sensor descriptions. `cumulated` marks
ever-increasing totals (documented as `Wh_Σ` / `sec_Σ`), which map to Home
Assistant's `total_increasing` state class.

```python
from fenecon_modbus import REGISTERS, REGISTERS_BY_KEY

REGISTERS_BY_KEY["grid_active_power"].unit  # Unit.WATT
REGISTERS_BY_KEY["grid_buy_active_energy"].cumulated  # True
[(r.address, r.name, r.key, r.unit) for r in REGISTERS]
```

| Address | Name | Type | Unit | Field |
|---|---|---|---|---|
| 101 | _meta/SystemTimeUtc | uint64 | s | `system_time_utc` |
| 200 | Component-ID | string16 |  | `component_id` |
| 222 | _sum/State | enum16 |  | `state` (`State`) |
| 302 | _sum/EssSoc | uint16 | % | `ess_soc` |
| 303 | _sum/EssActivePower | float32 | W | `ess_active_power` |
| 309 | _sum/EssReactivePower | float32 | var | `ess_reactive_power` |
| 315 | _sum/GridActivePower | float32 | W | `grid_active_power` |
| 317 | _sum/GridMinActivePower | float32 | W | `grid_min_active_power` |
| 319 | _sum/GridMaxActivePower | float32 | W | `grid_max_active_power` |
| 327 | _sum/ProductionActivePower | float32 | W | `production_active_power` |
| 329 | _sum/ProductionMaxActivePower | float32 | W | `production_max_active_power` |
| 331 | _sum/ProductionAcActivePower | float32 | W | `production_ac_active_power` |
| 339 | _sum/ProductionDcActualPower | float32 | W | `production_dc_actual_power` |
| 343 | _sum/ConsumptionActivePower | float32 | W | `consumption_active_power` |
| 345 | _sum/ConsumptionMaxActivePower | float32 | W | `consumption_max_active_power` |
| 351 | _sum/EssActiveChargeEnergy | float64 | Wh Σ | `ess_active_charge_energy` |
| 355 | _sum/EssActiveDischargeEnergy | float64 | Wh Σ | `ess_active_discharge_energy` |
| 359 | _sum/GridBuyActiveEnergy | float64 | Wh Σ | `grid_buy_active_energy` |
| 363 | _sum/GridSellActiveEnergy | float64 | Wh Σ | `grid_sell_active_energy` |
| 367 | _sum/ProductionActiveEnergy | float64 | Wh Σ | `production_active_energy` |
| 371 | _sum/ProductionAcActiveEnergy | float64 | Wh Σ | `production_ac_active_energy` |
| 375 | _sum/ProductionDcActiveEnergy | float64 | Wh Σ | `production_dc_active_energy` |
| 379 | _sum/ConsumptionActiveEnergy | float64 | Wh Σ | `consumption_active_energy` |
| 383 | _sum/EssDcChargeEnergy | float64 | Wh Σ | `ess_dc_charge_energy` |
| 387 | _sum/EssDcDischargeEnergy | float64 | Wh Σ | `ess_dc_discharge_energy` |
| 391–395 | _sum/EssActivePowerL1–L3 | float32 | W | `ess_active_power_l1` … `_l3` |
| 397–401 | _sum/GridActivePowerL1–L3 | float32 | W | `grid_active_power_l1` … `_l3` |
| 403–407 | _sum/ProductionAcActivePowerL1–L3 | float32 | W | `production_ac_active_power_l1` … `_l3` |
| 409–413 | _sum/ConsumptionActivePowerL1–L3 | float32 | W | `consumption_active_power_l1` … `_l3` |
| 415 | _sum/EssDischargePower | float32 | W | `ess_discharge_power` |
| 417 | _sum/GridMode | enum16 |  | `grid_mode` (`GridMode`: on-grid, off-grid, off-grid genset) |
| 418 | _sum/GridModeOffGridTime | float32 | s Σ | `grid_mode_off_grid_time` |
| 420 | _sum/EssCapacity | float32 | Wh | `ess_capacity` |

All registers are read-only and are read with function code 03 (Read Holding
Registers). Addresses are zero-based, as in the documentation. Only addresses
listed in the protocol are requested. Data points are combined into one request
when they are adjacent or separated only by documented reserved/meta registers,
so `read_data()` needs 4 requests and `read_device_info()` needs 1.

The per-phase values, `GridModeOffGridTime` and `EssCapacity` come from the
protocol of a FEMS running OpenEMS 2026.10.1 and are not in the public Fenecon
table. A FEMS with much older firmware may not provide them.

### Exceptions

| Exception | Raised when |
|---|---|
| `FeneconError` | Base class of all errors |
| `FeneconConnectionError` | The FEMS cannot be reached or the connection was lost |
| `FeneconTimeoutError` | The FEMS did not respond in time (subclass of `FeneconConnectionError`) |
| `FeneconInvalidResponseError` | Modbus exception response, or incomplete or undecodable data |

## Development

```bash
uv sync
uv run pytest
uv run mypy src tests
uv run ruff check src tests
```
