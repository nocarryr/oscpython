import asyncio
import pytest

from oscpython import AddressSpace, Bundle, Message, Client, TimeTag
from oscpython.transport import DatagramServer

class DgramProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.queue = asyncio.Queue()
    def datagram_received(self, data, addr):
        print(f'datagram_received: {addr}')
        self.queue.put_nowait((data, addr))

@pytest.fixture
async def datagram_server(request):
    marker = request.node.get_closest_marker('listen_address')
    if marker is None:
        listen_address = None
    else:
        listen_address = Client.from_tuple(marker.args[:2])
    server = DatagramServer(listen_address=listen_address)
    await server.open()
    yield server
    # print('closing server')
    await server.close()
    # print('server closed')

@pytest.mark.asyncio
# @pytest.mark.listen_address('127.0.0.1', 9002)
async def test_udp_send(datagram_server, unused_tcp_port):

    async def get_queue_item(queue, timeout=10):
        return await asyncio.wait_for(queue.get(), timeout)


    loop = asyncio.get_event_loop()
    server = datagram_server

    root, node1 = server.address_space.create_from_address('/foo/bar/baz1')
    root, node2 = server.address_space.create_from_address('/foo/bar/baz2')

    client_address = Client.from_tuple(('127.0.0.1', unused_tcp_port))
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DgramProtocol(),
        client_address.to_tuple(),
    )

    msg1 = node1.create_message(1, 2, remote_client=client_address)
    msg2 = node2.create_message('a', 'b', remote_client=client_address)

    print(f'msg1.send: {msg1!r}')
    await server.send_packet(msg1)
    print(f'msg2.send: {msg2!r}')
    await server.send_packet(msg2)

    print('queue.get')
    rx_item = await get_queue_item(protocol.queue)

    data, addr = rx_item
    rx_client = Client.from_tuple(addr)
    assert rx_client.port == server.listen_address.port
    assert data == msg1.build_packet()

    protocol.queue.task_done()

    print('queue.get')
    rx_item = await get_queue_item(protocol.queue)

    data, addr = rx_item
    rx_client = Client.from_tuple(addr)
    assert rx_client.port == server.listen_address.port
    assert data == msg2.build_packet()

    protocol.queue.task_done()

    tt1 = TimeTag.now()
    tt2 = TimeTag(seconds=tt1.seconds + 1, fraction=tt1.fraction)
    bun = node1.create_bundled_message(1, 2, timetag=tt1, remote_client=client_address)
    bun.add_packet(node2.create_bundled_message('a', 'b', timetag=tt2, remote_client=client_address))

    print(f'bun.send: {bun!r}')
    await server.send_packet(bun)
    print('queue.get')
    rx_item = await get_queue_item(protocol.queue)

    data, addr = rx_item
    rx_client = Client.from_tuple(addr)
    assert rx_client.port == server.listen_address.port
    assert data == bun.build_packet()

    protocol.queue.task_done()

    print('closing')
    transport.close()
    # await server.close()
    print('closed')


@pytest.mark.asyncio
@pytest.mark.listen_address('127.0.0.1', 9002)
async def test_udp_recv(datagram_server, unused_tcp_port):
    loop = asyncio.get_event_loop()

    class Listener:
        def __init__(self, node):
            self.node = node
            node.add_callback(self.callback)
            assert node.has_callbacks
            self.result = None
            self.event = asyncio.Event()
        async def wait(self, timeout=10):
            await asyncio.wait_for(self.event.wait(), timeout)
            self.event.clear()
            r = self.result
            self.result = None
            return r
        def callback(self, node, message, timetag):
            self.result = (node, message, timetag)
            self.event.set()

    server = datagram_server
    # server = DatagramServer(listen_address=Client.from_tuple(('127.0.0.1', 9000)))
    # await server.open()

    root, node1 = server.address_space.create_from_address('/foo/bar/baz1')
    root, node2 = server.address_space.create_from_address('/foo/bar/baz2')

    client_address = Client.from_tuple(('127.0.0.1', unused_tcp_port))
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DgramProtocol(),
        client_address.to_tuple(),
    )

    msg1 = node1.create_message(1, 2, remote_client=client_address)
    msg2 = node2.create_message('a', 'b', remote_client=client_address)

    listener1 = Listener(node1)
    listener2 = Listener(node2)

    print('msg1.send')
    transport.sendto(msg1.build_packet(), server.listen_address.to_tuple())
    print('msg2.send')
    transport.sendto(msg2.build_packet(), server.listen_address.to_tuple())

    print('listener.wait')
    result = await listener1.wait()
    rx_node, rx_msg, rx_timetag = result
    assert rx_node is node1
    assert rx_msg == msg1

    print('listener.wait')
    result = await listener2.wait()
    rx_node, rx_msg, rx_timetag = result
    assert rx_node is node2
    assert rx_msg == msg2

    tt1 = TimeTag.now()
    tt2 = TimeTag(seconds=tt1.seconds + 1, fraction=tt1.fraction)
    bun = node1.create_bundled_message(1, 2, timetag=tt1, remote_client=server.listen_address)
    bun.add_packet(node2.create_bundled_message('a', 'b', timetag=tt2, remote_client=server.listen_address))

    print('bun.send')
    transport.sendto(bun.build_packet(), server.listen_address.to_tuple())

    print('listener.wait')
    result1 = await listener1.wait()
    dispatch_ts1 = loop.time()
    result2 = await listener2.wait()
    dispatch_ts2 = loop.time()

    rx_node, rx_msg, rx_timetag1 = result1
    assert rx_node is node1
    assert rx_msg.build_packet() == msg1.build_packet()
    assert rx_msg.timetag == tt1

    rx_node, rx_msg, rx_timetag2 = result2
    assert rx_node is node2
    assert rx_msg.build_packet() == msg2.build_packet()
    assert rx_msg.timetag == tt2

    assert rx_timetag1 == rx_timetag2
    assert dispatch_ts2 - dispatch_ts1 == pytest.approx(1, 1e-2)

    print('closing')
    transport.close()
    # await server.close()
    print('closed')
