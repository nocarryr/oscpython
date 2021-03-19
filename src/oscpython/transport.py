# from loguru import logger
from typing import Optional, Tuple, ClassVar
import asyncio
from dataclasses import dataclass, field

from oscpython.common import Client, TimeTag
from oscpython.address import Address, AddressSpace, AddressNode
from oscpython.messages import Packet, Message, Bundle, PacketStartError

@dataclass
class QueueItem:
    """Item used in :attr:`BaseServer.rx_queue` and :attr:`BaseServer.tx_queue`
    """
    data: bytes #: The incoming or outgoing data
    addr: Tuple[str, int] #: The remote address as a tuple of (host, port)
    timetag: TimeTag = field(default_factory=TimeTag.now)
    """Timestamp of when the item was created

    For incoming data, this indicates the time of reception
    """

@dataclass(order=True)
class QueuedBundle:
    """Item to store bundles in a :class:`asyncio.PriorityQueue` sorted
    by :attr:`bundle_timetag`
    """
    bundle_timetag: TimeTag
    """The :attr:`~.messages.Bundle.timetag` value of the :attr:`bundle`.
    This is duplicated solely for sorting purposes
    """

    rx_timetag: Optional[TimeTag] = field(compare=False)
    """The timestamp of when the bundle was received
    """

    bundle: Optional[Bundle] = field(compare=False)
    """The :class:`~.messages.Bundle` instance
    """

class MessageHandler:
    """Handles dispatching packets to an :class:`~.address.AddressSpace`

    This is instanciated and managed by :class:`BaseServer`

    Arguments:
        address_space: The value for :attr:`address_space`
    """

    address_space: AddressSpace
    """The :class:`~.address.AddressSpace` for the handler"""

    queued_bundles: asyncio.PriorityQueue
    """A queue for :class:`QueuedBundle` items whose
    :attr:`~QueuedBundle.bundle_timetag` is in the future
    """

    running: bool
    """``True`` if the handler is running"""

    loop: asyncio.BaseEventLoop

    def __init__(self, address_space: AddressSpace):
        self.address_space = address_space
        self.queued_bundles = asyncio.PriorityQueue()
        self.queued_bundle_evt = asyncio.Event()
        self.running = False
        self._dispatch_loop_task = None
        self.loop = asyncio.get_event_loop()

    async def open(self):
        """Start background tasks needed for queue management
        """
        if self.running:
            return
        self.running = True
        self._dispatch_loop_task = asyncio.create_task(self.dispatch_loop())

    async def close(self):
        """Stop dispatching and exit all background tasks
        """
        if not self.running:
            return
        self.running = False
        t = self._dispatch_loop_task
        self._dispatch_loop_task = None
        if t is not None:
            qitem = QueuedBundle(
                bundle_timetag=TimeTag.Immediately, bundle=None, rx_timetag=None,
            )
            await self.queued_bundles.put(qitem)
            self.queued_bundle_evt.set()
            await t

    async def handle_packet(self, packet: Packet, timetag: TimeTag):
        """Handle an incoming :class:`~.messages.Packet`

        If the packet is a :class:`~.messages.Message`, the :attr:`address_space`
        is searched for any matching :class:`nodes <.address.AddressNode>`
        and the :meth:`~.address.AddressNode.dispatch` method will be called.

        If the packet is a :class:`~.messages.Bundle`, this method will be called
        recursively for all of the :attr:`~.messages.Bundle.packets` contained in
        the bundle.

        Arguments:
            packet: A :class:`~.messages.Message` or :class:`~.messages.Bundle`
                received from the network
            timetag: Timestamp of when the data was received. This is the
                :attr:`~QueueItem.timetag` attribute of the :class:`QueueItem`
                containing the packet data, **not** the
                :attr:`~.messages.Message.timetag` of the packet itself
        """
        if not self.running:
            return
        tasks = []
        if isinstance(packet, Message):
            for node in self.address_space.match(packet.address):
                node.dispatch(packet, timetag)
        elif isinstance(packet, Bundle):
            if packet.timetag > TimeTag.now():
                qitem = QueuedBundle(
                    rx_timetag=timetag,
                    bundle_timetag=packet.timetag,
                    bundle=packet,
                )
                await self.queued_bundles.put(qitem)
                self.queued_bundle_evt.set()
                return
            for item in packet:
                tasks.append(self.handle_packet(item, timetag))
        else: # pragma: no cover
            raise ValueError('Must be either a Message or Bundle')
        if len(tasks):
            await asyncio.gather(*tasks)

    # @logger.catch
    async def dispatch_loop(self):
        """Consume from :attr:`queued_bundles` and dispatch them according to
        their timetags

        This runs as long as :attr:`running` is True and the :class:`asyncio.Task`
        for it is managed by the :meth:`open` and :meth:`close` methods.
        """
        async def wait_for_evt(timeout=None):
            try:
                await asyncio.wait_for(self.queued_bundle_evt.wait(), timeout)
                self.queued_bundle_evt.clear()
            except asyncio.TimeoutError:
                return False
            return True
        while self.running:
            item = await self.queued_bundles.get()
            if item.bundle is None or not self.running:
                self.queued_bundles.task_done()
                break
            now = TimeTag.now()
            if item.bundle_timetag > now:
                await self.queued_bundles.put(item)
                timeout = item.bundle_timetag.float_seconds - now.float_seconds
                await wait_for_evt(timeout)
                continue
            self.queued_bundle_evt.clear()
            self.queued_bundles.task_done()
            await self.handle_packet(item.bundle, item.rx_timetag)


class BaseServer:
    """Base server class

    Arguments:
        listen_address: Value for :attr:`listen_address`. If not provided,
            defaults to :attr:`default_listen_address`
        address_space: Value for :attr:`address_space`. If not provided,
            an empty one will be created.
    """

    default_listen_address: ClassVar[Client] = Client(address='0.0.0.0', port=9000)
    """Default value for :attr:`listen_address`
    """

    listen_address: Client
    """The address and port to bind the server to
    """

    running: bool
    """``True`` if the server is running
    """

    rx_queue: asyncio.Queue
    """A :class:`~asyncio.Queue` for incoming data as :class:`QueueItem` instances
    """

    tx_queue: asyncio.Queue
    """A :class:`~asyncio.Queue` for outgoing data as :class:`QueueItem` instances
    """

    loop: asyncio.BaseEventLoop

    def __init__(self,
                 listen_address: Optional[Client] = None,
                 address_space: Optional[AddressSpace] = None):

        if listen_address is None:
            listen_address = self.default_listen_address
        self.listen_address = listen_address
        if address_space is None:
            address_space = AddressSpace()
        self.__address_space = address_space
        self.__message_handler = MessageHandler(address_space)
        self.running = False
        self.rx_queue = asyncio.Queue()
        self.tx_queue = asyncio.Queue()
        self._tx_loop_task = None
        self._rx_loop_task = None
        self.loop = asyncio.get_event_loop()

    @property
    def address_space(self) -> AddressSpace:
        """The :class:`~.address.AddressSpace` associated with the server
        """
        return self.__address_space

    @property
    def message_handler(self) -> MessageHandler:
        """The :class:`MessageHandler` for the server
        """
        return self.__message_handler

    async def send_packet(self, packet: Packet):
        """Send either a :class:`~.messages.Message` or :class:`~.messages.Bundle`

        The :attr:`~.messages.Packet.remote_client` in the given packet is used
        as the destination host address and port.

        Arguments:
            packet: The packet to send
        """
        data = packet.build_packet()
        addr = packet.remote_client.to_tuple()
        await self.tx_queue.put(QueueItem(data=data, addr=addr))

    async def open(self):
        """Open the server connections and start all background tasks

        Calls :meth:`open_endpoint` and creates tasks for :meth:`tx_loop`
        and :meth:`rx_loop`.
        """
        if self.running:
            return
        self.running = True
        await self.open_endpoint()
        self._tx_loop_task = asyncio.create_task(self.tx_loop())
        self._rx_loop_task = asyncio.create_task(self.rx_loop())
        await self.message_handler.open()

    async def close(self):
        """Stop all background tasks and close all connections

        Calls :meth:`close_endpoint` and stops the :meth:`tx_loop` and
        :meth:`rx_loop` tasks.
        """
        if not self.running:
            return
        self.running = False

        await self.message_handler.close()

        t = self._tx_loop_task
        self._tx_loop_task = None
        if t is not None:
            await self.tx_queue.put(None)
            await t

        t = self._rx_loop_task
        self._rx_loop_task = None
        if t is not None:
            await self.rx_queue.put(None)
            await t

        await self.close_endpoint()

    # @logger.catch
    async def tx_loop(self):
        """Wait for items on :attr:`tx_queue` and send them
        using :meth:`send_queue_item`

        This runs as long as :attr:`running` is True and the task for it is
        managed by the :meth:`open` and :meth:`close` methods
        """
        while self.running:
            item = await self.tx_queue.get()
            if item is None or not self.running:
                self.tx_queue.task_done()
                break
            r = await self.send_queue_item(item)
            if r:
                self.tx_queue.task_done()

    # @logger.catch
    async def rx_loop(self):
        """Wait for items on :attr:`rx_queue` and pass them to :attr:`message_handler`
        using :meth:`MessageHandler.handle_packet`.

        This runs as long as :attr:`running` is True and the task for it is
        managed by the :meth:`open` and :meth:`close` methods
        """
        while self.running:
            item = await self.rx_queue.get()
            if item is None or not self.running:
                self.rx_queue.task_done()
                break

            client = Client.from_tuple(item.addr)
            remaining = item.data
            tasks = []
            while len(remaining):
                try:
                    packet, remaining = Packet.parse(remaining, remote_client=client)
                except PacketStartError:
                    break
                tasks.append(self.message_handler.handle_packet(packet, item.timetag))
            if len(tasks):
                await asyncio.gather(*tasks)
            self.rx_queue.task_done()

    async def open_endpoint(self):
        """Open implementation-specific items for communication

        Called from the :meth:`open` method
        """
        raise NotImplementedError

    async def close_endpoint(self):
        """Close any implementation-specific communication items

        Called from the :meth:`close` method
        """
        raise NotImplementedError

    async def send_queue_item(self, item: QueueItem) -> bool:
        """Handle transmission of a :class:`QueueItem's <QueueItem>` bytestring

        Returns:
            bool:
                True if the item was sent
        """
        raise NotImplementedError

class DatagramProtocol(asyncio.DatagramProtocol):
    """Asyncio :class:`~asyncio.Protocol` for datagram communication
    """
    rx_queue: asyncio.Queue
    """The parent server's :attr:`~BaseServer.rx_queue`"""

    def __init__(self, rx_queue: asyncio.Queue):
        self.rx_queue = rx_queue
        self.connect_evt = asyncio.Event()

    def connection_made(self, transport):
        self.connect_evt.set()

    # @logger.catch
    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        """Place the incoming data on the :attr:`rx_queue`
        """
        self.rx_queue.put_nowait(QueueItem(data=data, addr=addr))

class DatagramServer(BaseServer):
    """An OSC Client/Server using UDP
    """
    transport: Optional[asyncio.DatagramTransport]
    """Datagram transport created by :meth:`~asyncio.loop.create_datagram_endpoint`
    """
    protocol: Optional[DatagramProtocol]
    """Protocol created by :meth:`~asyncio.loop.create_datagram_endpoint`
    """
    def __init__(self,
                 listen_address: Optional[Client] = None,
                 address_space: Optional[AddressSpace] = None):

        super().__init__(listen_address, address_space)
        self.transport = None
        self.protocol = None

    async def open_endpoint(self):
        t, p = await self.loop.create_datagram_endpoint(
            lambda: DatagramProtocol(self.rx_queue),
            self.listen_address.to_tuple(),
        )
        self.transport, self.protocol = t, p
        await self.protocol.connect_evt.wait()

    async def close_endpoint(self):
        self.transport.close()
        self.transport = None
        self.protocol = None

    async def send_queue_item(self, item: QueueItem) -> bool:
        if self.transport is None:
            return False
        self.transport.sendto(item.data, item.addr)
        return True
