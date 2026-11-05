"""Asynchronous Modbus/TCP client for FENECON FEMS."""

import asyncio
import logging
from types import TracebackType
from typing import Any, Self

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException

from .exceptions import FeneconConnectionError, FeneconInvalidResponseError, FeneconTimeoutError
from .models import FeneconData, FeneconDeviceInfo
from .registers import (
    DEVICE_INFO_REGISTERS,
    OPENEMS_HASH,
    OPENEMS_HASH_REGISTER,
    REGISTERS,
    ReadBlock,
    Value,
    build_read_blocks,
    decode_block,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_TIMEOUT = 5.0

_DATA_BLOCKS = build_read_blocks(REGISTERS)
_DEVICE_INFO_BLOCKS = build_read_blocks((OPENEMS_HASH_REGISTER, *DEVICE_INFO_REGISTERS))


class FeneconModbusClient:
    """Read the documented data points of a FEMS via Modbus/TCP.

    The client connects lazily: every read (re)establishes the
    connection when needed, so a dropped connection is recovered on the next
    poll. On any communication error the connection is closed and the error is
    raised as a :class:`~fenecon_modbus.exceptions.FeneconError` subclass.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        unit_id: int = DEFAULT_UNIT_ID,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._client: AsyncModbusTcpClient | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Whether a Modbus/TCP connection is currently open."""
        return self._client is not None and self._client.connected

    async def connect(self) -> None:
        """Open the connection to the FEMS.

        :raises FeneconTimeoutError: if the connection attempt timed out.
        :raises FeneconConnectionError: if the FEMS could not be reached.
        """
        async with self._lock:
            await self._connect()

    async def close(self) -> None:
        """Close the connection. Safe to call when not connected."""
        async with self._lock:
            self._close()

    async def read_data(self) -> FeneconData:
        """Read all ``_sum`` data points and the FEMS system time.

        :raises FeneconTimeoutError: if the FEMS did not answer in time.
        :raises FeneconConnectionError: if the connection failed or was lost.
        :raises FeneconInvalidResponseError: if the response could not be decoded.
        """
        values = await self._read(_DATA_BLOCKS)
        return FeneconData(**values)  # type: ignore[arg-type]

    async def read_device_info(self) -> FeneconDeviceInfo:
        """Read the identification data (manufacturer, model, serial numbers, OpenEMS version).

        These values do not change at runtime, so reading them once is enough.
        This also verifies that the server is an OpenEMS Modbus/TCP API.

        :raises FeneconTimeoutError: if the FEMS did not answer in time.
        :raises FeneconConnectionError: if the connection failed or was lost.
        :raises FeneconInvalidResponseError: if the response could not be decoded
            or the server is not an OpenEMS Modbus/TCP API.
        """
        values = await self._read(_DEVICE_INFO_BLOCKS)
        openems_hash = values.pop(OPENEMS_HASH_REGISTER.key)
        if openems_hash != OPENEMS_HASH:
            raise FeneconInvalidResponseError(
                f"Unexpected value {openems_hash!r} in register 0, expected {OPENEMS_HASH:#06x} (OpenEMS)"
            )
        return FeneconDeviceInfo(**values)  # type: ignore[arg-type]

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _connect(self) -> None:
        self._close()
        # Automatic reconnects are disabled; reconnecting happens on the next read.
        client = AsyncModbusTcpClient(
            self.host,
            port=self.port,
            timeout=self.timeout,
            retries=0,
            reconnect_delay=0,
        )
        self._client = client
        try:
            async with asyncio.timeout(self.timeout):
                connected = await client.connect()
        except TimeoutError as err:
            self._close()
            raise FeneconTimeoutError(f"Timeout connecting to {self.host}:{self.port}") from err
        except (OSError, ModbusException) as err:
            self._close()
            raise FeneconConnectionError(f"Error connecting to {self.host}:{self.port}: {err}") from err
        if not connected:
            self._close()
            raise FeneconConnectionError(f"Could not connect to {self.host}:{self.port}")
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)

    async def _read(self, blocks: tuple[ReadBlock, ...]) -> dict[str, Value]:
        async with self._lock:
            if not self.connected:
                await self._connect()
            values: dict[str, Value] = {}
            try:
                for block in blocks:
                    values.update(decode_block(block, await self._read_block(block)))
            except FeneconInvalidResponseError:
                raise
            except BaseException:
                self._close()
                raise
        return values

    def _close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    async def _read_block(self, block: ReadBlock) -> list[int]:
        assert self._client is not None
        try:
            async with asyncio.timeout(self.timeout):
                response: Any = await self._client.read_holding_registers(
                    block.address, count=block.count, device_id=self.unit_id
                )
        except TimeoutError as err:
            raise FeneconTimeoutError(f"Timeout reading {block.count} registers at {block.address}") from err
        except ModbusIOException as err:
            # pymodbus raises this when no response arrived within its timeout.
            raise FeneconTimeoutError(f"No response reading {block.count} registers at {block.address}: {err}") from err
        except (ConnectionException, OSError) as err:
            raise FeneconConnectionError(f"Connection lost: {err}") from err
        except ModbusException as err:
            raise FeneconInvalidResponseError(
                f"Error reading {block.count} registers at {block.address}: {err}"
            ) from err

        if response is None or response.isError():
            raise FeneconInvalidResponseError(
                f"Error response reading {block.count} registers at {block.address}: {response}"
            )
        registers = getattr(response, "registers", None)
        if not isinstance(registers, list):
            raise FeneconInvalidResponseError(f"Response for address {block.address} contains no registers")
        return registers
