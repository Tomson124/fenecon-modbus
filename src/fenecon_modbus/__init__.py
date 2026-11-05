"""Asynchronous Python client for Fenecon solar (FEMS) Modbus."""

from .client import DEFAULT_PORT, DEFAULT_TIMEOUT, DEFAULT_UNIT_ID, FeneconModbusClient
from .exceptions import (
    FeneconConnectionError,
    FeneconError,
    FeneconInvalidResponseError,
    FeneconTimeoutError,
)
from .models import FeneconData, FeneconDeviceInfo, GridMode, State
from .registers import DEVICE_INFO_REGISTERS, REGISTERS, REGISTERS_BY_KEY, DataType, Register, Unit

__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "DEFAULT_UNIT_ID",
    "DEVICE_INFO_REGISTERS",
    "REGISTERS",
    "REGISTERS_BY_KEY",
    "DataType",
    "FeneconConnectionError",
    "FeneconData",
    "FeneconDeviceInfo",
    "FeneconError",
    "FeneconInvalidResponseError",
    "FeneconModbusClient",
    "FeneconTimeoutError",
    "GridMode",
    "Register",
    "State",
    "Unit",
]
