"""Register map and decoding tests."""

import dataclasses
import itertools
import math

import pytest
from conftest import float32_words, float64_words, string16_words, uint64_words

from fenecon_modbus import FeneconData, FeneconDeviceInfo, FeneconInvalidResponseError, GridMode, State
from fenecon_modbus.registers import (
    DEVICE_INFO_REGISTERS,
    OPENEMS_HASH_REGISTER,
    REGISTERS,
    REGISTERS_BY_KEY,
    RESERVED_REGISTERS,
    DataType,
    Unit,
    build_read_blocks,
    decode_block,
)

# Full Modbus protocol downloaded from the FEMS (OpenEMS 2026.10.1), row by row:
# (address, name, type, unit). Rows "Hash of"/"Length of block"/"Reserved"
# carry no data and are listed with unit None.
PROTOCOL = [
    (0, 'Hash of "OpenEMS"', "uint16", None),
    (1, 'Length of block "_meta"', "uint16", None),
    (2, "OpenEMS Version Major", "uint16", None),
    (3, "OpenEMS Version Minor", "uint16", None),
    (4, "OpenEMS Version Patch", "uint16", None),
    (5, "Manufacturer", "string16", None),
    (21, "Manufacturer Model", "string16", None),
    (37, "Manufacturer Options", "string16", None),
    (53, "Manufacturer Version", "string16", None),
    (69, "Manufacturer Serial Number", "string16", None),
    (85, "Manufacturer EMS Serial Number", "string16", None),
    (101, "_meta/SystemTimeUtc", "uint64", "s"),
    (200, "Component-ID", "string16", None),
    (216, 'Length of block "_sum"', "uint16", None),
    (220, 'Hash of "OpenemsComponent"', "uint16", None),
    (221, 'Length of block "OpenemsComponent"', "uint16", None),
    (222, "_sum/State", "enum16", None),
    (300, 'Hash of "Sum"', "uint16", None),
    (301, 'Length of block "Sum"', "uint16", None),
    (302, "_sum/EssSoc", "uint16", "%"),
    (303, "_sum/EssActivePower", "float32", "W"),
    (305, "Reserved", "float32", None),
    (307, "Reserved", "float32", None),
    (309, "_sum/EssReactivePower", "float32", "var"),
    (311, "Reserved", "float32", None),
    (313, "Reserved", "float32", None),
    (315, "_sum/GridActivePower", "float32", "W"),
    (317, "_sum/GridMinActivePower", "float32", "W"),
    (319, "_sum/GridMaxActivePower", "float32", "W"),
    (321, "Reserved", "float32", None),
    (323, "Reserved", "float32", None),
    (325, "Reserved", "float32", None),
    (327, "_sum/ProductionActivePower", "float32", "W"),
    (329, "_sum/ProductionMaxActivePower", "float32", "W"),
    (331, "_sum/ProductionAcActivePower", "float32", "W"),
    (333, "Reserved", "float32", None),
    (335, "Reserved", "float32", None),
    (337, "Reserved", "float32", None),
    (339, "_sum/ProductionDcActualPower", "float32", "W"),
    (341, "Reserved", "float32", None),
    (343, "_sum/ConsumptionActivePower", "float32", "W"),
    (345, "_sum/ConsumptionMaxActivePower", "float32", "W"),
    (347, "Reserved", "float32", None),
    (349, "Reserved", "float32", None),
    (351, "_sum/EssActiveChargeEnergy", "float64", "Wh"),
    (355, "_sum/EssActiveDischargeEnergy", "float64", "Wh"),
    (359, "_sum/GridBuyActiveEnergy", "float64", "Wh"),
    (363, "_sum/GridSellActiveEnergy", "float64", "Wh"),
    (367, "_sum/ProductionActiveEnergy", "float64", "Wh"),
    (371, "_sum/ProductionAcActiveEnergy", "float64", "Wh"),
    (375, "_sum/ProductionDcActiveEnergy", "float64", "Wh"),
    (379, "_sum/ConsumptionActiveEnergy", "float64", "Wh"),
    (383, "_sum/EssDcChargeEnergy", "float64", "Wh"),
    (387, "_sum/EssDcDischargeEnergy", "float64", "Wh"),
    (391, "_sum/EssActivePowerL1", "float32", "W"),
    (393, "_sum/EssActivePowerL2", "float32", "W"),
    (395, "_sum/EssActivePowerL3", "float32", "W"),
    (397, "_sum/GridActivePowerL1", "float32", "W"),
    (399, "_sum/GridActivePowerL2", "float32", "W"),
    (401, "_sum/GridActivePowerL3", "float32", "W"),
    (403, "_sum/ProductionAcActivePowerL1", "float32", "W"),
    (405, "_sum/ProductionAcActivePowerL2", "float32", "W"),
    (407, "_sum/ProductionAcActivePowerL3", "float32", "W"),
    (409, "_sum/ConsumptionActivePowerL1", "float32", "W"),
    (411, "_sum/ConsumptionActivePowerL2", "float32", "W"),
    (413, "_sum/ConsumptionActivePowerL3", "float32", "W"),
    (415, "_sum/EssDischargePower", "float32", "W"),
    (417, "_sum/GridMode", "enum16", None),
    (418, "_sum/GridModeOffGridTime", "float32", "s"),
    (420, "_sum/EssCapacity", "float32", "Wh"),
]

# Units documented as cumulated (Wh_Σ, sec_Σ).
CUMULATED = {351, 355, 359, 363, 367, 371, 375, 379, 383, 387, 418}

_SIZES = {"uint16": 1, "enum16": 1, "uint64": 4, "float32": 2, "float64": 4, "string16": 16}


def test_register_map_matches_protocol() -> None:
    data = [
        (r.address, r.name, str(r.data_type), r.unit and str(r.unit))
        for r in (OPENEMS_HASH_REGISTER, *DEVICE_INFO_REGISTERS, *REGISTERS)
    ]
    reserved: list[tuple[int, str, str, str | None]] = [
        (address, name, "uint16" if count == 1 else "float32", None) for address, count, name in RESERVED_REGISTERS
    ]
    assert sorted(data + reserved) == PROTOCOL


def test_every_protocol_row_is_covered_once() -> None:
    covered = [r.address for r in (OPENEMS_HASH_REGISTER, *DEVICE_INFO_REGISTERS, *REGISTERS)]
    covered += [address for address, _, _ in RESERVED_REGISTERS]
    assert sorted(covered) == [row[0] for row in PROTOCOL]


def test_reserved_sizes_match_types() -> None:
    by_address = {row[0]: row for row in PROTOCOL}
    for address, count, _ in RESERVED_REGISTERS:
        assert _SIZES[by_address[address][2]] == count


def test_protocol_rows_do_not_overlap() -> None:
    for current, following in itertools.pairwise(PROTOCOL):
        assert current[0] + _SIZES[current[2]] <= following[0]


def test_cumulated_flags() -> None:
    assert {r.address for r in REGISTERS if r.cumulated} == CUMULATED


def test_dataclass_fields_match_registers() -> None:
    assert [f.name for f in dataclasses.fields(FeneconData)] == [r.key for r in REGISTERS]
    assert [f.name for f in dataclasses.fields(FeneconDeviceInfo)] == [r.key for r in DEVICE_INFO_REGISTERS]
    assert set(REGISTERS_BY_KEY) == {r.key for r in REGISTERS}


def test_enums_match_protocol() -> None:
    assert {s.value: s for s in State} == {0: State.OK, 1: State.INFO, 2: State.WARNING, 3: State.FAULT}
    assert {m.value: m for m in GridMode} == {
        1: GridMode.ON_GRID,
        2: GridMode.OFF_GRID,
        3: GridMode.OFF_GRID_GENSET,
    }


@pytest.mark.parametrize(
    ("data_type", "count"),
    [
        (DataType.UINT16, 1),
        (DataType.ENUM16, 1),
        (DataType.UINT64, 4),
        (DataType.FLOAT32, 2),
        (DataType.FLOAT64, 4),
        (DataType.STRING16, 16),
    ],
)
def test_register_counts(data_type: DataType, count: int) -> None:
    assert data_type.size == count


def test_read_blocks_cover_only_documented_addresses() -> None:
    data_blocks = build_read_blocks(REGISTERS)
    info_blocks = build_read_blocks((OPENEMS_HASH_REGISTER, *DEVICE_INFO_REGISTERS))
    assert [(b.address, b.count) for b in data_blocks] == [(101, 4), (200, 16), (222, 1), (302, 120)]
    assert [(b.address, b.count) for b in info_blocks] == [(0, 101)]

    documented = {row[0] + i for row in PROTOCOL for i in range(_SIZES[row[2]])}
    for block in (*data_blocks, *info_blocks):
        assert block.count <= 125
        assert set(range(block.address, block.address + block.count)) <= documented


def test_read_blocks_do_not_bridge_undocumented_gaps() -> None:
    # 217..219 are not in the protocol, so 200 and 222 must stay separate.
    blocks = build_read_blocks([REGISTERS_BY_KEY["component_id"], REGISTERS_BY_KEY["state"]])
    assert [(b.address, b.count) for b in blocks] == [(200, 16), (222, 1)]


class TestDecode:
    def test_uint16(self) -> None:
        assert REGISTERS_BY_KEY["ess_soc"].decode([0]) == 0
        assert REGISTERS_BY_KEY["ess_soc"].decode([55]) == 55
        assert REGISTERS_BY_KEY["ess_soc"].decode([100]) == 100

    def test_uint16_undefined_or_outside_documented_range_is_none(self) -> None:
        assert REGISTERS_BY_KEY["ess_soc"].decode([101]) is None
        assert REGISTERS_BY_KEY["ess_soc"].decode([0xFFFF]) is None
        assert DEVICE_INFO_REGISTERS[0].decode([0xFFFF]) is None
        assert DEVICE_INFO_REGISTERS[0].decode([2026]) == 2026

    def test_enum16(self) -> None:
        assert REGISTERS_BY_KEY["state"].decode([3]) is State.FAULT
        assert REGISTERS_BY_KEY["grid_mode"].decode([2]) is GridMode.OFF_GRID
        assert REGISTERS_BY_KEY["grid_mode"].decode([3]) is GridMode.OFF_GRID_GENSET

    @pytest.mark.parametrize("word", [0xFFFF, 4])
    def test_enum16_undefined_or_unknown_is_none(self, word: int) -> None:
        assert REGISTERS_BY_KEY["state"].decode([word]) is None
        assert REGISTERS_BY_KEY["grid_mode"].decode([word]) is None

    def test_uint64(self) -> None:
        register = REGISTERS_BY_KEY["system_time_utc"]
        assert register.decode(uint64_words(1_793_620_800)) == 1_793_620_800
        assert register.decode([0x0001, 0x0000, 0x0000, 0x0000]) == 1 << 48  # high word first

    def test_uint64_undefined_is_none(self) -> None:
        assert REGISTERS_BY_KEY["system_time_utc"].decode([0xFFFF] * 4) is None

    @pytest.mark.parametrize("value", [0.0, 1234.5, -1234.5, -0.25, 30000.0])
    def test_float32_with_sign(self, value: float) -> None:
        assert REGISTERS_BY_KEY["grid_active_power"].decode(float32_words(value)) == value

    def test_float32_is_big_endian_high_word_first(self) -> None:
        # -1250.5 == 0xC49C5000
        assert REGISTERS_BY_KEY["ess_active_power"].decode([0xC49C, 0x5000]) == -1250.5
        assert REGISTERS_BY_KEY["ess_active_power"].decode([0x5000, 0xC49C]) != -1250.5

    @pytest.mark.parametrize("value", [0.0, 9876543.25, 123456789012.5, -1.5])
    def test_float64(self, value: float) -> None:
        assert REGISTERS_BY_KEY["grid_buy_active_energy"].decode(float64_words(value)) == value

    def test_float64_is_big_endian(self) -> None:
        # 1000.0 == 0x408F400000000000
        words = [0x408F, 0x4000, 0x0000, 0x0000]
        assert REGISTERS_BY_KEY["consumption_active_energy"].decode(words) == 1000.0

    def test_documented_undefined_floats_are_none(self) -> None:
        assert REGISTERS_BY_KEY["grid_active_power"].decode([0x7FC0, 0x0000]) is None
        assert REGISTERS_BY_KEY["grid_buy_active_energy"].decode([0x7FF8, 0, 0, 0]) is None
        assert REGISTERS_BY_KEY["grid_active_power"].decode(float32_words(math.nan)) is None

    def test_string16(self) -> None:
        assert REGISTERS_BY_KEY["component_id"].decode(string16_words("_sum")) == "_sum"
        assert DEVICE_INFO_REGISTERS[3].decode(string16_words("FENECON GmbH")) == "FENECON GmbH"

    def test_undefined_string16_is_none(self) -> None:
        assert REGISTERS_BY_KEY["component_id"].decode([0] * 16) is None

    @pytest.mark.parametrize("words", [[], [1, 2]])
    def test_wrong_register_count_raises(self, words: list[int]) -> None:
        with pytest.raises(FeneconInvalidResponseError):
            REGISTERS_BY_KEY["ess_soc"].decode(words)

    def test_out_of_range_word_raises(self) -> None:
        with pytest.raises(FeneconInvalidResponseError):
            REGISTERS_BY_KEY["ess_soc"].decode([0x10000])

    def test_units(self) -> None:
        assert REGISTERS_BY_KEY["ess_soc"].unit is Unit.PERCENT
        assert REGISTERS_BY_KEY["ess_reactive_power"].unit is Unit.VOLT_AMPERE_REACTIVE
        assert REGISTERS_BY_KEY["grid_sell_active_energy"].unit is Unit.WATT_HOUR
        assert REGISTERS_BY_KEY["ess_capacity"].unit is Unit.WATT_HOUR
        assert REGISTERS_BY_KEY["grid_mode_off_grid_time"].unit is Unit.SECOND
        assert REGISTERS_BY_KEY["state"].unit is None


def test_decode_block_short_response_raises() -> None:
    block = build_read_blocks([REGISTERS_BY_KEY["ess_soc"], REGISTERS_BY_KEY["ess_active_power"]])[0]
    with pytest.raises(FeneconInvalidResponseError):
        decode_block(block, [50, 0])


def test_decode_block_skips_reserved_registers() -> None:
    block = build_read_blocks([REGISTERS_BY_KEY["ess_active_power"], REGISTERS_BY_KEY["ess_reactive_power"]])[0]
    assert (block.address, block.count) == (303, 8)  # 305..308 reserved
    words = [*float32_words(-500.0), 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, *float32_words(7.5)]
    assert decode_block(block, words) == {"ess_active_power": -500.0, "ess_reactive_power": 7.5}
