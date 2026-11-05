"""Public API tests with a mocked pymodbus client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from conftest import SAMPLE_VALUES, FakeFems
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException
from pymodbus.pdu import ExceptionResponse

from fenecon_modbus import (
    FeneconConnectionError,
    FeneconData,
    FeneconDeviceInfo,
    FeneconInvalidResponseError,
    FeneconModbusClient,
    FeneconTimeoutError,
    GridMode,
    State,
)


async def test_read_data_returns_decoded_values(modbus_client: MagicMock) -> None:
    async with FeneconModbusClient("192.168.0.20") as client:
        data = await client.read_data()

    assert isinstance(data, FeneconData)
    expected = {**SAMPLE_VALUES, "state": State.OK, "grid_mode": GridMode.ON_GRID}
    for key, value in expected.items():
        assert getattr(data, key) == value, key
    assert data.state is State.OK
    assert data.grid_mode is GridMode.ON_GRID
    assert isinstance(data.ess_soc, int)


async def test_client_uses_configured_connection_parameters(modbus_client: MagicMock, fems: FakeFems) -> None:
    client = FeneconModbusClient("fems.local", 5020, unit_id=7, timeout=2.5)
    await client.read_data()

    modbus_client.factory.assert_called_once()
    args, kwargs = modbus_client.factory.call_args
    assert args == ("fems.local",)
    assert kwargs["port"] == 5020
    assert kwargs["timeout"] == 2.5
    assert kwargs["reconnect_delay"] == 0
    assert {device_id for _, _, device_id in fems.requests} == {7}


async def test_defaults(modbus_client: MagicMock) -> None:
    client = FeneconModbusClient("192.168.0.20")
    assert (client.port, client.unit_id) == (502, 1)


async def test_reads_documented_addresses_with_function_code_3(modbus_client: MagicMock, fems: FakeFems) -> None:
    await FeneconModbusClient("h").read_data()
    assert [(a, c) for a, c, _ in fems.requests] == [(101, 4), (200, 16), (222, 1), (302, 120)]


async def test_read_device_info(modbus_client: MagicMock, fems: FakeFems) -> None:
    info = await FeneconModbusClient("h").read_device_info()

    assert info == FeneconDeviceInfo(
        openems_version_major=2026,
        openems_version_minor=10,
        openems_version_patch=1,
        manufacturer="FENECON GmbH",
        manufacturer_model="FEMS",
        manufacturer_options=None,
        manufacturer_version=None,
        manufacturer_serial_number=None,
        manufacturer_ems_serial_number="fems88426",
    )
    assert info.openems_version == "2026.10.1"
    assert [(a, c) for a, c, _ in fems.requests] == [(0, 101)]


async def test_read_device_info_undefined_version(modbus_client: MagicMock, fems: FakeFems) -> None:
    fems.set("openems_version_patch", 0xFFFF)
    info = await FeneconModbusClient("h").read_device_info()
    assert info.openems_version_patch is None
    assert info.openems_version is None


async def test_read_device_info_rejects_non_openems_server(modbus_client: MagicMock, fems: FakeFems) -> None:
    fems.set("openems_hash", 0x1234)
    client = FeneconModbusClient("h")
    with pytest.raises(FeneconInvalidResponseError, match="OpenEMS"):
        await client.read_device_info()
    assert client.connected  # the device answered; the connection stays usable


async def test_connect_and_close(modbus_client: MagicMock) -> None:
    client = FeneconModbusClient("h")
    assert not client.connected
    await client.connect()
    assert client.connected
    await client.close()
    assert not client.connected
    modbus_client.close.assert_called()
    await client.close()  # idempotent


async def test_read_data_connects_lazily_and_reuses_connection(modbus_client: MagicMock) -> None:
    client = FeneconModbusClient("h")
    await client.read_data()
    await client.read_data()
    assert modbus_client.connect.await_count == 1


async def test_reconnects_after_connection_drop(modbus_client: MagicMock) -> None:
    client = FeneconModbusClient("h")
    await client.read_data()
    modbus_client.connected = False  # e.g. FEMS rebooted
    await client.read_data()
    assert modbus_client.connect.await_count == 2


async def test_undefined_values_become_none(modbus_client: MagicMock, fems: FakeFems) -> None:
    fems.set("grid_active_power", float("nan"))
    fems.set("ess_soc", 0xFFFF)
    fems.set("state", 0xFFFF)
    fems.set("grid_mode", 0xFFFF)
    fems.set("system_time_utc", 0xFFFF_FFFF_FFFF_FFFF)
    fems.set_words(200, [0] * 16)
    data = await FeneconModbusClient("h").read_data()
    assert data.grid_active_power is None
    assert data.ess_soc is None
    assert data.state is None
    assert data.grid_mode is None
    assert data.system_time_utc is None
    assert data.component_id is None
    assert data.production_active_power == SAMPLE_VALUES["production_active_power"]


class TestConnectErrors:
    async def test_connect_returns_false(self, modbus_client: MagicMock) -> None:
        modbus_client.connect = AsyncMock(return_value=False)
        client = FeneconModbusClient("h")
        with pytest.raises(FeneconConnectionError):
            await client.connect()
        assert not client.connected

    async def test_connect_raises_os_error(self, modbus_client: MagicMock) -> None:
        modbus_client.connect = AsyncMock(side_effect=OSError("unreachable"))
        with pytest.raises(FeneconConnectionError) as err:
            await FeneconModbusClient("h").read_data()
        assert not isinstance(err.value, FeneconTimeoutError)

    async def test_connect_timeout(self, modbus_client: MagicMock) -> None:
        async def hang() -> bool:
            await asyncio.sleep(10)
            return True

        modbus_client.connect = AsyncMock(side_effect=hang)
        client = FeneconModbusClient("h", timeout=0.01)
        with pytest.raises(FeneconTimeoutError):
            await client.connect()
        modbus_client.close.assert_called()


class TestReadErrors:
    @pytest.mark.parametrize(
        ("exception", "expected"),
        [
            (ConnectionException("lost"), FeneconConnectionError),
            (ConnectionResetError("reset"), FeneconConnectionError),
            (ModbusIOException("no response"), FeneconTimeoutError),
            (TimeoutError(), FeneconTimeoutError),
            (ModbusException("garbage"), FeneconInvalidResponseError),
        ],
    )
    async def test_exceptions_are_translated(
        self,
        modbus_client: MagicMock,
        exception: Exception,
        expected: type[Exception],
    ) -> None:
        modbus_client.read_holding_registers = AsyncMock(side_effect=exception)
        with pytest.raises(expected) as err:
            await FeneconModbusClient("h").read_data()
        assert type(err.value) is expected
        assert err.value.__cause__ is exception

    @pytest.mark.parametrize("exception", [ConnectionException("lost"), ModbusIOException("no response")])
    async def test_connection_is_closed_and_recovered_after_error(
        self, modbus_client: MagicMock, fems: FakeFems, exception: Exception
    ) -> None:
        client = FeneconModbusClient("h")
        modbus_client.read_holding_registers = AsyncMock(side_effect=exception)
        with pytest.raises(FeneconConnectionError):
            await client.read_data()
        assert not client.connected

        modbus_client.read_holding_registers = AsyncMock(side_effect=fems.read_holding_registers)
        data = await client.read_data()
        assert data.ess_soc == SAMPLE_VALUES["ess_soc"]
        assert modbus_client.connect.await_count == 2

    async def test_read_timeout(self, modbus_client: MagicMock) -> None:
        async def hang(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(10)

        modbus_client.read_holding_registers = AsyncMock(side_effect=hang)
        client = FeneconModbusClient("h", timeout=0.01)
        with pytest.raises(FeneconTimeoutError):
            await client.read_data()
        assert not client.connected

    async def test_modbus_exception_response(self, modbus_client: MagicMock) -> None:
        # Exception code 2: illegal data address
        modbus_client.read_holding_registers = AsyncMock(return_value=ExceptionResponse(0x03, 2))
        with pytest.raises(FeneconInvalidResponseError):
            await FeneconModbusClient("h").read_data()

    async def test_incomplete_response(self, modbus_client: MagicMock, fems: FakeFems) -> None:
        async def truncated(address: int, *, count: int = 1, device_id: int = 1) -> object:
            response = await fems.read_holding_registers(address, count=count, device_id=device_id)
            response.registers = response.registers[:-1]
            return response

        modbus_client.read_holding_registers = AsyncMock(side_effect=truncated)
        with pytest.raises(FeneconInvalidResponseError):
            await FeneconModbusClient("h").read_data()

    async def test_response_without_registers(self, modbus_client: MagicMock) -> None:
        response = MagicMock(spec=["isError"])
        response.isError.return_value = False
        modbus_client.read_holding_registers = AsyncMock(return_value=response)
        with pytest.raises(FeneconInvalidResponseError):
            await FeneconModbusClient("h").read_data()

    async def test_none_response(self, modbus_client: MagicMock) -> None:
        modbus_client.read_holding_registers = AsyncMock(return_value=None)
        with pytest.raises(FeneconInvalidResponseError):
            await FeneconModbusClient("h").read_data()

    async def test_cancellation_closes_connection(self, modbus_client: MagicMock) -> None:
        started = asyncio.Event()

        async def hang(*args: object, **kwargs: object) -> None:
            started.set()
            await asyncio.sleep(10)

        modbus_client.read_holding_registers = AsyncMock(side_effect=hang)
        client = FeneconModbusClient("h")
        task = asyncio.create_task(client.read_data())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not client.connected


async def test_concurrent_reads_are_serialized(modbus_client: MagicMock, fems: FakeFems) -> None:
    active = 0
    max_active = 0

    async def tracking(address: int, *, count: int = 1, device_id: int = 1) -> object:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return await fems.read_holding_registers(address, count=count, device_id=device_id)

    modbus_client.read_holding_registers = AsyncMock(side_effect=tracking)
    client = FeneconModbusClient("h")
    await asyncio.gather(client.read_data(), client.read_data())
    assert max_active == 1
