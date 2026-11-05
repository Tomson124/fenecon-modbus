"""Register map of the FEMS Modbus/TCP read interface and decoding helpers.

Sources:

- "FEMS App Modbus/TCP lesend", Tabelle 2 "Modbus-Tabelle Komponente Sum"
  https://docs.fenecon.de/de/fems/fems-app/App_ModbusTCP_read_access.html#_modbus_tabelle
- The full Modbus protocol of a FEMS (OpenEMS 2026.10.1), downloaded via
  online monitoring -> Einstellungen -> Anlagenprofil -> ctrlApiModbusTcp ->
  "PROTOKOLL HERUNTERLADEN". It contains the ``_meta`` header, the per-phase
  ``_sum`` values, ``GridModeOffGridTime``, ``EssCapacity``, the sign
  conventions and the encoding of undefined values.

Addresses are zero-based, exactly as listed in the documentation. All
registers are read-only (``RO``). No scaling factors are defined: values are
transmitted directly in their unit. Multi-register values are decoded
big-endian (high word first), the Modbus default.
"""

import math
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from .exceptions import FeneconInvalidResponseError
from .models import GridMode, State

type Value = int | float | str | IntEnum | None


class DataType(StrEnum):
    """Register data types used in the documentation."""

    UINT16 = "uint16"
    ENUM16 = "enum16"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    STRING16 = "string16"

    @property
    def size(self) -> int:
        """Number of 16-bit registers occupied by this type."""
        return _REGISTER_COUNT[self]


_REGISTER_COUNT = {
    DataType.UINT16: 1,
    DataType.ENUM16: 1,
    DataType.UINT64: 4,
    DataType.FLOAT32: 2,
    DataType.FLOAT64: 4,
    DataType.STRING16: 16,
}

# Values the FEMS reports for "undefined" (protocol, sheet 2). Undefined floats
# are NaN and undefined strings are all zero; both are handled during decoding.
UNDEFINED_UINT16 = 0xFFFF
UNDEFINED_UINT64 = 0xFFFF_FFFF_FFFF_FFFF


class Unit(StrEnum):
    """Units used in the documentation."""

    PERCENT = "%"
    WATT = "W"
    VOLT_AMPERE_REACTIVE = "var"
    WATT_HOUR = "Wh"
    SECOND = "s"


@dataclass(frozen=True, slots=True, kw_only=True)
class Register:
    """A single documented data point."""

    address: int
    name: str
    """Name as written in the documentation."""
    key: str
    """Attribute name in the returned dataclass."""
    data_type: DataType
    unit: Unit | None = None
    cumulated: bool = False
    """``True`` for ever-increasing totals (documented as ``Wh_Σ`` / ``sec_Σ``)."""
    enum: type[IntEnum] | None = None
    valid_range: tuple[int, int] | None = None
    """Documented value range (inclusive); values outside decode to ``None``."""

    @property
    def count(self) -> int:
        """Number of 16-bit registers occupied by this data point."""
        return self.data_type.size

    def decode(self, registers: Sequence[int]) -> Value:
        """Decode raw register words into the documented value."""
        if len(registers) != self.count:
            raise FeneconInvalidResponseError(
                f"{self.name} ({self.address}) expects {self.count} registers, got {len(registers)}"
            )
        if any(not 0 <= word <= 0xFFFF for word in registers):
            raise FeneconInvalidResponseError(f"{self.name} ({self.address}) received non 16-bit register values")
        raw = struct.pack(f">{self.count}H", *registers)

        match self.data_type:
            case DataType.UINT16:
                value = registers[0]
                if value == UNDEFINED_UINT16:
                    return None
                if self.valid_range and not (self.valid_range[0] <= value <= self.valid_range[1]):
                    return None
                return value
            case DataType.ENUM16:
                assert self.enum is not None
                try:
                    return self.enum(registers[0])
                except ValueError:  # includes the undefined value 0xFFFF
                    return None
            case DataType.UINT64:
                integer: int = struct.unpack(">Q", raw)[0]
                return None if integer == UNDEFINED_UINT64 else integer
            case DataType.FLOAT32 | DataType.FLOAT64:
                fmt = ">f" if self.data_type is DataType.FLOAT32 else ">d"
                number: float = struct.unpack(fmt, raw)[0]
                return None if math.isnan(number) else number
            case DataType.STRING16:
                text = raw.decode("ascii", errors="replace").strip("\x00 ")
                return text or None


def _power(address: int, name: str, key: str) -> Register:
    return Register(address=address, name=name, key=key, data_type=DataType.FLOAT32, unit=Unit.WATT)


def _energy(address: int, name: str, key: str) -> Register:
    return Register(
        address=address, name=name, key=key, data_type=DataType.FLOAT64, unit=Unit.WATT_HOUR, cumulated=True
    )


def _string(address: int, name: str, key: str) -> Register:
    return Register(address=address, name=name, key=key, data_type=DataType.STRING16)


OPENEMS_HASH = 0x6201
"""Expected content of register 0 (``Hash of "OpenEMS"``)."""

OPENEMS_HASH_REGISTER = Register(address=0, name='Hash of "OpenEMS"', key="openems_hash", data_type=DataType.UINT16)

DEVICE_INFO_REGISTERS: tuple[Register, ...] = (
    Register(address=2, name="OpenEMS Version Major", key="openems_version_major", data_type=DataType.UINT16),
    Register(address=3, name="OpenEMS Version Minor", key="openems_version_minor", data_type=DataType.UINT16),
    Register(address=4, name="OpenEMS Version Patch", key="openems_version_patch", data_type=DataType.UINT16),
    _string(5, "Manufacturer", "manufacturer"),
    _string(21, "Manufacturer Model", "manufacturer_model"),
    _string(37, "Manufacturer Options", "manufacturer_options"),
    _string(53, "Manufacturer Version", "manufacturer_version"),
    _string(69, "Manufacturer Serial Number", "manufacturer_serial_number"),
    _string(85, "Manufacturer EMS Serial Number", "manufacturer_ems_serial_number"),
)
"""Identification data of the ``_meta`` header, ordered by address."""

REGISTERS: tuple[Register, ...] = (
    Register(
        address=101, name="_meta/SystemTimeUtc", key="system_time_utc", data_type=DataType.UINT64, unit=Unit.SECOND
    ),
    _string(200, "Component-ID", "component_id"),
    Register(address=222, name="_sum/State", key="state", data_type=DataType.ENUM16, enum=State),
    Register(
        address=302,
        name="_sum/EssSoc",
        key="ess_soc",
        data_type=DataType.UINT16,
        unit=Unit.PERCENT,
        valid_range=(0, 100),
    ),
    _power(303, "_sum/EssActivePower", "ess_active_power"),
    Register(
        address=309,
        name="_sum/EssReactivePower",
        key="ess_reactive_power",
        data_type=DataType.FLOAT32,
        unit=Unit.VOLT_AMPERE_REACTIVE,
    ),
    _power(315, "_sum/GridActivePower", "grid_active_power"),
    _power(317, "_sum/GridMinActivePower", "grid_min_active_power"),
    _power(319, "_sum/GridMaxActivePower", "grid_max_active_power"),
    _power(327, "_sum/ProductionActivePower", "production_active_power"),
    _power(329, "_sum/ProductionMaxActivePower", "production_max_active_power"),
    _power(331, "_sum/ProductionAcActivePower", "production_ac_active_power"),
    _power(339, "_sum/ProductionDcActualPower", "production_dc_actual_power"),
    _power(343, "_sum/ConsumptionActivePower", "consumption_active_power"),
    _power(345, "_sum/ConsumptionMaxActivePower", "consumption_max_active_power"),
    _energy(351, "_sum/EssActiveChargeEnergy", "ess_active_charge_energy"),
    _energy(355, "_sum/EssActiveDischargeEnergy", "ess_active_discharge_energy"),
    _energy(359, "_sum/GridBuyActiveEnergy", "grid_buy_active_energy"),
    _energy(363, "_sum/GridSellActiveEnergy", "grid_sell_active_energy"),
    _energy(367, "_sum/ProductionActiveEnergy", "production_active_energy"),
    _energy(371, "_sum/ProductionAcActiveEnergy", "production_ac_active_energy"),
    _energy(375, "_sum/ProductionDcActiveEnergy", "production_dc_active_energy"),
    _energy(379, "_sum/ConsumptionActiveEnergy", "consumption_active_energy"),
    _energy(383, "_sum/EssDcChargeEnergy", "ess_dc_charge_energy"),
    _energy(387, "_sum/EssDcDischargeEnergy", "ess_dc_discharge_energy"),
    _power(391, "_sum/EssActivePowerL1", "ess_active_power_l1"),
    _power(393, "_sum/EssActivePowerL2", "ess_active_power_l2"),
    _power(395, "_sum/EssActivePowerL3", "ess_active_power_l3"),
    _power(397, "_sum/GridActivePowerL1", "grid_active_power_l1"),
    _power(399, "_sum/GridActivePowerL2", "grid_active_power_l2"),
    _power(401, "_sum/GridActivePowerL3", "grid_active_power_l3"),
    _power(403, "_sum/ProductionAcActivePowerL1", "production_ac_active_power_l1"),
    _power(405, "_sum/ProductionAcActivePowerL2", "production_ac_active_power_l2"),
    _power(407, "_sum/ProductionAcActivePowerL3", "production_ac_active_power_l3"),
    _power(409, "_sum/ConsumptionActivePowerL1", "consumption_active_power_l1"),
    _power(411, "_sum/ConsumptionActivePowerL2", "consumption_active_power_l2"),
    _power(413, "_sum/ConsumptionActivePowerL3", "consumption_active_power_l3"),
    _power(415, "_sum/EssDischargePower", "ess_discharge_power"),
    Register(address=417, name="_sum/GridMode", key="grid_mode", data_type=DataType.ENUM16, enum=GridMode),
    Register(
        address=418,
        name="_sum/GridModeOffGridTime",
        key="grid_mode_off_grid_time",
        data_type=DataType.FLOAT32,
        unit=Unit.SECOND,
        cumulated=True,
    ),
    Register(address=420, name="_sum/EssCapacity", key="ess_capacity", data_type=DataType.FLOAT32, unit=Unit.WATT_HOUR),
)
"""Data points returned by :meth:`FeneconModbusClient.read_data`, ordered by address."""

REGISTERS_BY_KEY: dict[str, Register] = {register.key: register for register in REGISTERS}

RESERVED_REGISTERS: tuple[tuple[int, int, str], ...] = (
    (1, 1, 'Length of block "_meta"'),
    (216, 1, 'Length of block "_sum"'),
    (220, 1, 'Hash of "OpenemsComponent"'),
    (221, 1, 'Length of block "OpenemsComponent"'),
    (300, 1, 'Hash of "Sum"'),
    (301, 1, 'Length of block "Sum"'),
    *((address, 2, "Reserved") for address in (305, 307, 311, 313, 321, 323, 325, 333, 335, 337, 341, 347, 349)),
)
"""Documented ``(address, count, name)`` entries that carry no data.

They are never decoded, but may be read over to combine data points into
fewer requests.
"""

_RESERVED_ADDRESSES = frozenset(address + offset for address, count, _ in RESERVED_REGISTERS for offset in range(count))

MAX_REGISTERS_PER_READ = 125
"""Modbus limit for a single "read holding registers" request."""


@dataclass(frozen=True, slots=True)
class ReadBlock:
    """A contiguous range of documented registers fetched with one request."""

    address: int
    count: int
    registers: tuple[Register, ...]


def build_read_blocks(registers: Iterable[Register]) -> tuple[ReadBlock, ...]:
    """Group registers into as few requests as possible.

    Registers are merged when they directly follow each other or when the gap
    between them consists only of documented reserved registers, so no
    undocumented address is ever requested.
    """
    blocks: list[ReadBlock] = []
    current: list[Register] = []
    for register in sorted(registers, key=lambda r: r.address):
        if current:
            start = current[0].address
            end = current[-1].address + current[-1].count
            gap_is_reserved = all(address in _RESERVED_ADDRESSES for address in range(end, register.address))
            fits = register.address + register.count - start <= MAX_REGISTERS_PER_READ
            if register.address >= end and gap_is_reserved and fits:
                current.append(register)
                continue
            blocks.append(_to_block(current))
        current = [register]
    if current:
        blocks.append(_to_block(current))
    return tuple(blocks)


def _to_block(registers: list[Register]) -> ReadBlock:
    start = registers[0].address
    end = registers[-1].address + registers[-1].count
    return ReadBlock(address=start, count=end - start, registers=tuple(registers))


def decode_block(block: ReadBlock, words: Sequence[int]) -> dict[str, Value]:
    """Decode the response words of a :class:`ReadBlock` keyed by register key."""
    if len(words) != block.count:
        raise FeneconInvalidResponseError(
            f"Expected {block.count} registers from address {block.address}, got {len(words)}"
        )
    values: dict[str, Value] = {}
    for register in block.registers:
        offset = register.address - block.address
        values[register.key] = register.decode(words[offset : offset + register.count])
    return values
