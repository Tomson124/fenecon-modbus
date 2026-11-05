"""Typed data returned by the client."""

from dataclasses import dataclass
from enum import IntEnum


class State(IntEnum):
    """Register 222 ``_sum/State``."""

    OK = 0
    INFO = 1
    WARNING = 2
    FAULT = 3


class GridMode(IntEnum):
    """Register 417 ``_sum/GridMode``."""

    ON_GRID = 1
    OFF_GRID = 2
    OFF_GRID_GENSET = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class FeneconDeviceInfo:
    """Static identification data from the ``_meta`` header block."""

    openems_version_major: int | None
    """2 ``OpenEMS Version Major``."""
    openems_version_minor: int | None
    """3 ``OpenEMS Version Minor``."""
    openems_version_patch: int | None
    """4 ``OpenEMS Version Patch``."""
    manufacturer: str | None
    """5 ``Manufacturer``."""
    manufacturer_model: str | None
    """21 ``Manufacturer Model``."""
    manufacturer_options: str | None
    """37 ``Manufacturer Options``."""
    manufacturer_version: str | None
    """53 ``Manufacturer Version``."""
    manufacturer_serial_number: str | None
    """69 ``Manufacturer Serial Number``."""
    manufacturer_ems_serial_number: str | None
    """85 ``Manufacturer EMS Serial Number``."""

    @property
    def openems_version(self) -> str | None:
        """OpenEMS version as ``major.minor.patch``, if fully known."""
        parts = (self.openems_version_major, self.openems_version_minor, self.openems_version_patch)
        if any(part is None for part in parts):
            return None
        return ".".join(str(part) for part in parts)


@dataclass(frozen=True, slots=True, kw_only=True)
class FeneconData:
    """Snapshot of all ``_sum`` data points plus the FEMS system time.

    Every field corresponds to exactly one register (see
    :data:`fenecon_modbus.registers.REGISTERS` for address, data type and unit).
    Values are already in their unit; ``None`` means the FEMS reported the
    value as undefined.

    Sign conventions (from the FEMS Modbus protocol): ESS power is negative
    while charging and positive while discharging; grid power is negative for
    feed-in (sell) and positive for consumption (buy); production is always
    positive.
    """

    system_time_utc: int | None
    """101 ``_meta/SystemTimeUtc``: seconds since 1970-01-01 00:00:00 UTC."""
    component_id: str | None
    """200 ``Component-ID``."""
    state: State | None
    """222 ``_sum/State``."""
    ess_soc: int | None
    """302 ``_sum/EssSoc`` in % (0..100)."""
    ess_active_power: float | None
    """303 ``_sum/EssActivePower`` in W, incl. excess DC-PV production of hybrid inverters."""
    ess_reactive_power: float | None
    """309 ``_sum/EssReactivePower`` in var."""
    grid_active_power: float | None
    """315 ``_sum/GridActivePower`` (grid exchange) in W."""
    grid_min_active_power: float | None
    """317 ``_sum/GridMinActivePower`` in W."""
    grid_max_active_power: float | None
    """319 ``_sum/GridMaxActivePower`` in W."""
    production_active_power: float | None
    """327 ``_sum/ProductionActivePower`` (total production) in W."""
    production_max_active_power: float | None
    """329 ``_sum/ProductionMaxActivePower`` in W."""
    production_ac_active_power: float | None
    """331 ``_sum/ProductionAcActivePower`` (AC sources) in W."""
    production_dc_actual_power: float | None
    """339 ``_sum/ProductionDcActualPower`` (DC sources) in W."""
    consumption_active_power: float | None
    """343 ``_sum/ConsumptionActivePower`` in W."""
    consumption_max_active_power: float | None
    """345 ``_sum/ConsumptionMaxActivePower`` in W."""
    ess_active_charge_energy: float | None
    """351 ``_sum/EssActiveChargeEnergy`` in Wh (cumulated)."""
    ess_active_discharge_energy: float | None
    """355 ``_sum/EssActiveDischargeEnergy`` in Wh (cumulated)."""
    grid_buy_active_energy: float | None
    """359 ``_sum/GridBuyActiveEnergy`` (grid consumption) in Wh (cumulated)."""
    grid_sell_active_energy: float | None
    """363 ``_sum/GridSellActiveEnergy`` (grid feed-in) in Wh (cumulated)."""
    production_active_energy: float | None
    """367 ``_sum/ProductionActiveEnergy`` in Wh (cumulated)."""
    production_ac_active_energy: float | None
    """371 ``_sum/ProductionAcActiveEnergy`` in Wh (cumulated)."""
    production_dc_active_energy: float | None
    """375 ``_sum/ProductionDcActiveEnergy`` in Wh (cumulated)."""
    consumption_active_energy: float | None
    """379 ``_sum/ConsumptionActiveEnergy`` in Wh (cumulated)."""
    ess_dc_charge_energy: float | None
    """383 ``_sum/EssDcChargeEnergy`` in Wh (cumulated)."""
    ess_dc_discharge_energy: float | None
    """387 ``_sum/EssDcDischargeEnergy`` in Wh (cumulated)."""
    ess_active_power_l1: float | None
    """391 ``_sum/EssActivePowerL1`` in W."""
    ess_active_power_l2: float | None
    """393 ``_sum/EssActivePowerL2`` in W."""
    ess_active_power_l3: float | None
    """395 ``_sum/EssActivePowerL3`` in W."""
    grid_active_power_l1: float | None
    """397 ``_sum/GridActivePowerL1`` in W."""
    grid_active_power_l2: float | None
    """399 ``_sum/GridActivePowerL2`` in W."""
    grid_active_power_l3: float | None
    """401 ``_sum/GridActivePowerL3`` in W."""
    production_ac_active_power_l1: float | None
    """403 ``_sum/ProductionAcActivePowerL1`` in W."""
    production_ac_active_power_l2: float | None
    """405 ``_sum/ProductionAcActivePowerL2`` in W."""
    production_ac_active_power_l3: float | None
    """407 ``_sum/ProductionAcActivePowerL3`` in W."""
    consumption_active_power_l1: float | None
    """409 ``_sum/ConsumptionActivePowerL1`` in W."""
    consumption_active_power_l2: float | None
    """411 ``_sum/ConsumptionActivePowerL2`` in W."""
    consumption_active_power_l3: float | None
    """413 ``_sum/ConsumptionActivePowerL3`` in W."""
    ess_discharge_power: float | None
    """415 ``_sum/EssDischargePower`` (actual AC-side battery discharge power) in W."""
    grid_mode: GridMode | None
    """417 ``_sum/GridMode``."""
    grid_mode_off_grid_time: float | None
    """418 ``_sum/GridModeOffGridTime``: total off-grid time in s (cumulated)."""
    ess_capacity: float | None
    """420 ``_sum/EssCapacity`` in Wh."""
