"""Shared test helpers: a fake FEMS register space and a mocked pymodbus client."""

import struct
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pymodbus.pdu.register_message import ReadHoldingRegistersResponse

from fenecon_modbus.registers import (
    DEVICE_INFO_REGISTERS,
    OPENEMS_HASH,
    OPENEMS_HASH_REGISTER,
    REGISTERS,
    RESERVED_REGISTERS,
    DataType,
    Register,
)

ALL_REGISTERS: dict[str, Register] = {r.key: r for r in (OPENEMS_HASH_REGISTER, *DEVICE_INFO_REGISTERS, *REGISTERS)}


def float32_words(value: float) -> list[int]:
    return list(struct.unpack(">2H", struct.pack(">f", value)))


def float64_words(value: float) -> list[int]:
    return list(struct.unpack(">4H", struct.pack(">d", value)))


def uint64_words(value: int) -> list[int]:
    return list(struct.unpack(">4H", struct.pack(">Q", value)))


def string16_words(value: str) -> list[int]:
    return list(struct.unpack(">16H", value.encode("ascii").ljust(32, b"\x00")))


# Values taken from the attached protocol where it lists them.
SAMPLE_DEVICE_INFO: dict[str, object] = {
    "openems_hash": OPENEMS_HASH,
    "openems_version_major": 2026,
    "openems_version_minor": 10,
    "openems_version_patch": 1,
    "manufacturer": "FENECON GmbH",
    "manufacturer_model": "FEMS",
    "manufacturer_options": "",
    "manufacturer_version": "",
    "manufacturer_serial_number": "",
    "manufacturer_ems_serial_number": "fems88426",
}

SAMPLE_VALUES: dict[str, object] = {
    "system_time_utc": 1_793_620_800,
    "component_id": "_sum",
    "state": 0,
    "ess_soc": 87,
    "ess_active_power": -1250.5,
    "ess_reactive_power": 12.25,
    "grid_active_power": -3400.0,
    "grid_min_active_power": -9800.0,
    "grid_max_active_power": 14500.0,
    "production_active_power": 5600.75,
    "production_max_active_power": 9900.0,
    "production_ac_active_power": 1200.0,
    "production_dc_actual_power": 4400.75,
    "consumption_active_power": 950.25,
    "consumption_max_active_power": 22000.0,
    "ess_active_charge_energy": 1234567.0,
    "ess_active_discharge_energy": 1134567.5,
    "grid_buy_active_energy": 9876543.25,
    "grid_sell_active_energy": 18765432.0,
    "production_active_energy": 45678901.0,
    "production_ac_active_energy": 5678901.0,
    "production_dc_active_energy": 40000000.0,
    "consumption_active_energy": 31234567.0,
    "ess_dc_charge_energy": 1300000.0,
    "ess_dc_discharge_energy": 1200000.0,
    "ess_active_power_l1": -416.5,
    "ess_active_power_l2": -417.0,
    "ess_active_power_l3": -417.0,
    "grid_active_power_l1": -1200.0,
    "grid_active_power_l2": -1100.0,
    "grid_active_power_l3": -1100.0,
    "production_ac_active_power_l1": 400.0,
    "production_ac_active_power_l2": 400.0,
    "production_ac_active_power_l3": 400.0,
    "consumption_active_power_l1": 300.25,
    "consumption_active_power_l2": 350.0,
    "consumption_active_power_l3": 300.0,
    "ess_discharge_power": -1250.5,
    "grid_mode": 1,
    "grid_mode_off_grid_time": 3600.0,
    "ess_capacity": 10000.0,
}


def encode(key: str, value: object) -> list[int]:
    register = ALL_REGISTERS[key]
    match register.data_type:
        case DataType.STRING16:
            return string16_words(str(value))
        case DataType.FLOAT32:
            return float32_words(float(value))  # type: ignore[arg-type]
        case DataType.FLOAT64:
            return float64_words(float(value))  # type: ignore[arg-type]
        case DataType.UINT64:
            return uint64_words(int(value))  # type: ignore[call-overload]
        case _:
            return [int(value)]  # type: ignore[call-overload]


class FakeFems:
    """Register space of a FEMS containing exactly the addresses of the protocol.

    Reading any other address raises ``KeyError``, so tests fail if the client
    requests an undocumented register.
    """

    def __init__(self) -> None:
        self.memory: dict[int, int] = {}
        self.requests: list[tuple[int, int, int]] = []
        for address, count, _ in RESERVED_REGISTERS:
            # Reserved floats are undefined (NaN); block meta data gets an arbitrary value.
            words = float32_words(float("nan")) if count == 2 else [0x1234]
            self.set_words(address, words)
        for key, value in (SAMPLE_DEVICE_INFO | SAMPLE_VALUES).items():
            self.set(key, value)

    def set(self, key: str, value: object) -> None:
        self.set_words(ALL_REGISTERS[key].address, encode(key, value))

    def set_words(self, address: int, words: list[int]) -> None:
        for offset, word in enumerate(words):
            self.memory[address + offset] = word

    async def read_holding_registers(
        self, address: int, *, count: int = 1, device_id: int = 1
    ) -> ReadHoldingRegistersResponse:
        self.requests.append((address, count, device_id))
        words = [self.memory[a] for a in range(address, address + count)]
        return ReadHoldingRegistersResponse(registers=words, dev_id=device_id)


@pytest.fixture
def fems() -> FakeFems:
    return FakeFems()


@pytest.fixture
def modbus_client(fems: FakeFems) -> Iterator[MagicMock]:
    """Patch pymodbus' AsyncModbusTcpClient with a mock backed by ``fems``."""
    mock = MagicMock()
    mock.connected = False

    async def connect() -> bool:
        mock.connected = True
        return True

    def close() -> None:
        mock.connected = False

    mock.connect = AsyncMock(side_effect=connect)
    mock.close = MagicMock(side_effect=close)
    mock.read_holding_registers = AsyncMock(side_effect=fems.read_holding_registers)

    with patch("fenecon_modbus.client.AsyncModbusTcpClient", return_value=mock) as cls:
        mock.factory = cls
        yield mock
