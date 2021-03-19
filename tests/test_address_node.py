import pytest
from oscpython.address import Address, AddressSpace, AddressNode
from oscpython import Client, TimeTag

def test_add_and_reparent():
    sp = AddressSpace()

    foo = sp.add_root('foo')
    assert foo.name == 'foo'
    assert foo.address.pattern == '/foo'
    assert 'foo' in sp
    assert foo.parent is None
    assert foo.is_root
    assert foo.root is foo
    assert foo.address_space is sp
    assert sp['foo'] is foo
    assert sp.add_root('foo') is foo
    assert len(sp) == 1
    assert len(foo) == 0

    bar = foo.add_child('bar')
    assert bar.name == 'bar'
    assert bar.address.pattern == '/foo/bar'
    assert 'bar' in foo
    assert foo['bar'] is bar
    assert foo.address_space is sp
    assert bar.parent is foo
    assert not bar.is_root
    assert bar.root is foo
    assert len(foo) == 1
    assert len(sp) == 1

    last_node = AddressNode('last')
    bar.add_child_instance(last_node)
    assert last_node.address.pattern == '/foo/bar/last'
    assert last_node.root is foo
    assert len(bar) == 1

    baz = sp.add_root('baz')
    assert baz.address.pattern == '/baz'
    assert 'baz' in sp
    assert baz.is_root
    assert len(sp) == 2


    bar.parent = baz
    assert bar.address.pattern == '/baz/bar'
    assert bar.address_space is sp
    assert bar.root is baz
    assert not bar.is_root
    assert len(foo) == 0
    assert len(bar) == 1

    assert last_node.address.pattern == '/baz/bar/last'
    assert last_node.address_space is sp
    assert not last_node.is_root
    assert last_node.root is baz

    all_addresses = ('/foo', '/baz', '/baz/bar', '/baz/bar/last')
    node_addrs = set()
    for node in sp.walk():
        print(node)
        assert node.address.pattern not in node_addrs
        node_addrs.add(node.address.pattern)
    assert set(node_addrs) == set(all_addresses)

def test_exceptions():
    class MyAddressNode(AddressNode):
        pass

    sp = AddressSpace()

    foo = sp.add_root('foo')
    assert sp.add_root('foo') is foo

    my_bar = foo.add_child('bar', cls=MyAddressNode)
    assert foo.add_child('bar', cls=MyAddressNode) is my_bar

    with pytest.raises(KeyError):
        sp.add_root('foo', cls=MyAddressNode)
    with pytest.raises(KeyError):
        sp.add_root_instance(AddressNode('foo'))
    with pytest.raises(KeyError):
        sp.add_root_instance(MyAddressNode('foo'))
    with pytest.raises(KeyError):
        sp.create_from_address('/foo', cls=MyAddressNode)

    with pytest.raises(KeyError):
        foo.add_child('bar')
    with pytest.raises(KeyError):
        foo.add_child_instance(AddressNode('bar'))
    with pytest.raises(KeyError):
        foo.add_child_instance(MyAddressNode('bar'))


    baz1 = MyAddressNode('baz')
    baz1.parent = my_bar
    assert baz1.address.pattern == '/foo/bar/baz'

    baz2 = MyAddressNode('baz')
    with pytest.raises(KeyError):
        baz2.parent = my_bar


def test_multiple_address_spaces():
    sp1 = AddressSpace()
    sp2 = AddressSpace()

    arm_addrs = (
        '/arm/left/hand',
        '/arm/right/hand',
    )
    leg_addrs = (
        '/leg/left/foot',
        '/leg/right/foot'
    )

    all_arm_addrs = (
        '/arm', '/arm/left', '/arm/right',
        '/arm/left/hand', '/arm/right/hand',
    )

    all_leg_addrs = (
        '/leg', '/leg/left', '/leg/right',
        '/leg/left/foot', '/leg/right/foot',
    )

    for addr in arm_addrs:
        sp1.create_from_address(addr)
    for addr in leg_addrs:
        sp2.create_from_address(addr)


    assert list(sp1.keys()) == ['arm']
    assert list(sp2.keys()) == ['leg']


    for addr in all_arm_addrs:
        node = sp1.find(addr)
        assert node.address.pattern == addr
        assert node.address_space is sp1
        if addr == '/arm':
            assert node.is_root
            assert node.name in sp1.keys()
        else:
            assert not node.is_root
            assert node.name in node.parent.keys()

            with pytest.raises(ValueError) as excinfo:
                node.address_space = sp2
            assert 'only root nodes' in str(excinfo.value).lower()

    for addr in all_leg_addrs:
        node = sp2.find(addr)
        assert node.address.pattern == addr
        assert node.address_space is sp2
        if addr == '/leg':
            assert node.is_root
            assert node.name in sp2.keys()
        else:
            assert not node.is_root
            assert node.name in node.parent.keys()

            with pytest.raises(ValueError) as excinfo:
                node.address_space = sp1
            assert 'only root nodes' in str(excinfo.value).lower()

    arm_node = sp1['arm']
    leg_node = sp2['leg']


    sp1.add_root_instance(leg_node)

    for addr in all_leg_addrs:
        assert sp2.find(addr) is None

        node = sp1.find(addr)
        assert node.address_space is sp1


    arm_node.address_space = sp2

    for addr in all_arm_addrs:
        assert sp1.find(addr) is None

        node = sp2.find(addr)
        assert node.address_space is sp2



def test_node_tree(message_addresses):
    message_addresses = set(message_addresses)

    sp = AddressSpace()
    all_addr_nodes = set()
    for addr in message_addresses:
        root, last_child = sp.create_from_address(addr)
        assert root.is_root
        if last_child is not root:
            assert not last_child.is_root
        all_addr_nodes.add(last_child)
        assert last_child.address.pattern == addr
        assert last_child.root is root
        assert root.find(addr) is last_child
        assert sp.find(addr) is last_child

        matched = 0
        for node in sp.match(addr):
            assert node is last_child
            matched += 1

        assert matched == 1


    assert len(message_addresses) ==  len(all_addr_nodes)

def test_packet_creation(message_addresses, random_arguments, faker):
    sp = AddressSpace()

    base_tt = TimeTag.now()

    for i, addr in enumerate(message_addresses):
        root, node = sp.create_from_address(addr)
        client = Client(address=faker.ipv4(), port=faker.port_number())
        args = tuple([next(random_arguments) for _ in range(3)])
        arg_vals = tuple([arg.value for arg in args])

        msg = node.create_message(*args, remote_client=client)
        assert msg.remote_client == client
        assert msg.address == node.address
        assert msg.address is not node.address
        assert tuple([arg.value for arg in msg]) == arg_vals

        tt = TimeTag(seconds=base_tt.seconds + i, fraction=base_tt.fraction)
        bun = node.create_bundled_message(*args, remote_client=client, timetag=tt)
        assert bun.timetag == tt
        assert bun.remote_client == client
        assert len(bun) == 1
        bun_msg = bun[0]
        assert bun_msg.address == node.address
        assert bun_msg.address is not node.address
        assert tuple([arg.value for arg in bun_msg]) == arg_vals

def test_node_dispatch(message_addresses, random_arguments, faker):

    class SpaceListener:
        def __init__(self, address_space):
            self.address_space = address_space
            self.results = []
            self.address_space.bind(on_message=self.callback)
        def get_result(self):
            r = self.results[0]
            self.results = self.results[1:]
            return r
        def callback(self, address, msg, timetag):
            self.results.append((address, msg, timetag))

    class NodeListener:
        def __init__(self):
            self.results = []
        def bind_to_node(self, node):
            self.results.clear()
            node.add_callback(self.callback)
        def unbind_node(self, node):
            node.remove_callback(self.callback)
            self.results.clear()
        def get_result(self):
            r = self.results[0]
            self.results = self.results[1:]
            return r
        def callback(self, node, msg, timetag):
            self.results.append((node, msg, timetag))

    sp = AddressSpace()
    sp_listener = SpaceListener(sp)
    node_listener = NodeListener()

    base_tt = TimeTag.now()

    for i, addr in enumerate(message_addresses):
        tt = TimeTag(seconds=base_tt.seconds + i, fraction=base_tt.fraction)

        root, node = sp.create_from_address(addr)
        assert not node.has_callbacks
        assert node.event_handler is None
        node_listener.bind_to_node(node)
        assert node.has_callbacks
        assert node.event_handler is not None

        client = Client(address=faker.ipv4(), port=faker.port_number())
        args = tuple([next(random_arguments) for _ in range(3)])
        arg_vals = tuple([arg.value for arg in args])

        msg = node.create_message(*args, remote_client=client)
        node.dispatch(msg, tt)

        sp_result = sp_listener.get_result()
        r_addr, r_msg, r_tt = sp_result
        assert r_addr == node.address
        assert r_msg == msg
        assert r_tt == tt

        node_result = node_listener.get_result()
        r_node, r_msg, r_tt = node_result
        assert r_node is node
        assert r_msg == msg
        assert r_tt == tt

        node_listener.unbind_node(node)
        assert not node.has_callbacks
        assert node.event_handler is None
