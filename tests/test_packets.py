import struct
import pytest

from oscpython import Packet, Message, Bundle, TimeTag
from oscpython.messages import (
    ParseError, PacketStartError, MessageStartError, BundleStartError,
)
from oscpython import arguments


def check_message_args(msg: Message, all_arg_bytes: bytes):
    for arg in msg:
        try:
            bytes_expected = arg.build_packet()
        except ValueError as exc:
            if 'Cannot pack empty argument' in str(exc):
                continue
            raise
        arg_bytes = all_arg_bytes[:len(bytes_expected)]
        print(f'arg={arg}: bytes_expected={bytes_expected}, arg_bytes={arg_bytes}')
        assert arg_bytes == bytes_expected
        all_arg_bytes = all_arg_bytes[len(bytes_expected):]

def check_parsed_message(expected_msg: Message, parsed_msg: Message):
    assert parsed_msg.address == expected_msg.address
    assert len(parsed_msg) == len(expected_msg)
    for parg, marg in zip(parsed_msg, expected_msg):
        assert parg.__class__ is marg.__class__
        if isinstance(parg, (arguments.Float32Argument, arguments.Float64Argument)):
            assert parg.value == pytest.approx(marg.value)
        elif isinstance(parg, arguments.TimeTagArgument):
            assert parg.get_pack_value() == marg.get_pack_value()
        else:
            assert parg == marg

def test_message_arguments(message_args):
    address = '/foo'
    arg_values, typetags_expected = message_args
    typetags_length = len(typetags_expected)

    msg = Message.create(address, *arg_values)
    assert len(msg) == len(list(msg)) == len(msg.arguments)

    for i, arg in enumerate(msg):
        assert arg is msg.arguments[i]
        assert arg.value == msg[i] == arg_values[i]

    msg_bytes = msg.build_packet()
    assert len(msg_bytes) % 4 == 0
    address_bytes = msg_bytes[:8]
    assert address_bytes[:len(address)].decode() == msg.address.pattern == address
    typetag_bytes = msg_bytes[8:typetags_length+8]
    assert typetag_bytes == typetags_expected
    all_arg_bytes = msg_bytes[typetags_length+8:]
    print(f'all_arg_bytes = {all_arg_bytes}')
    check_message_args(msg, all_arg_bytes)

    parsed, remaining = Packet.parse(msg.build_packet())
    check_parsed_message(msg, parsed)


def test_bundle(message_args):
    arg_values, typetags_expected = message_args
    typetags_length = len(typetags_expected)

    bun = Bundle()
    assert bun.timetag == TimeTag.Immediately
    assert bun.timetag.seconds == 0
    assert bun.timetag.fraction == 1

    messages = (
        Message.create('/foo', *arg_values),
        Message.create('/bar/baz', *arg_values),
        Message.create('/no/args'),
    )
    msg_addrs = (
        b'/foo\x00\x00\x00\x00',
        b'/bar/baz\x00\x00\x00\x00',
        b'/no/args\x00\x00\x00\x00',
    )

    for msg in messages:
        bun.add_packet(msg)

    assert len(bun) == len(list(bun)) == len(messages) == len(bun.packets)

    for i, msg in enumerate(bun):
        assert msg is bun[i] is bun.packets[i]
        assert msg.parent_bundle is bun
        assert msg.parent_index == i

    bun_bytes = bun.build_packet()
    print(f'bun_bytes={bun_bytes}')
    assert len(bun_bytes) % 4 == 0
    assert bun_bytes.startswith(b'#bundle\x00')

    tt_bytes = bun_bytes[8:16]
    tt_val = struct.unpack('>Q', tt_bytes)[0]
    assert TimeTag.from_uint64(tt_val) == bun.timetag == TimeTag.Immediately
    assert tt_val == 1

    payload_bytes = bun_bytes[16:]
    all_msg_bytes = []
    all_msg_lengths = []

    while len(payload_bytes):
        msg_size = struct.unpack('>i', payload_bytes[:4])[0]
        print(f'msg_size={msg_size}')
        all_msg_lengths.append(msg_size)
        payload_bytes = payload_bytes[4:]
        msg_bytes = payload_bytes[:msg_size]
        payload_bytes = payload_bytes[msg_size:]
        all_msg_bytes.append(msg_bytes)

    assert len(all_msg_bytes) == len(messages)

    for msg, addr, msg_bytes, msg_size in zip(messages, msg_addrs, all_msg_bytes, all_msg_lengths):
        print(f'msg={msg}, msg_bytes={msg_bytes}')
        assert msg_bytes.startswith(addr)
        if msg.address.pattern == '/no/args':
            assert msg_bytes == addr
        else:
            start_ix = len(addr)
            end_ix = start_ix + len(typetags_expected)
            typetag_bytes = msg_bytes[start_ix:end_ix]
            assert typetag_bytes == typetags_expected
            start_ix = end_ix
            all_arg_bytes = msg_bytes[start_ix:]
            check_message_args(msg, all_arg_bytes)

        msg_repacked = msg.build_packet()
        assert msg_repacked == msg_bytes
        assert len(msg_repacked) == msg_size

    parsed, remaining = Packet.parse(bun_bytes)
    print(f'parsed={parsed}, remaining={remaining}')
    assert parsed.timetag == bun.timetag
    assert len(parsed.packets) == len(bun.packets)
    for parsed_pkt, bun_pkt in zip(parsed, bun):
        check_parsed_message(bun_pkt, parsed_pkt)


def test_bundle_timestamps(message_args, faker):
    arg_values, typetags_expected = message_args
    typetags_length = len(typetags_expected)

    msg_addrs = ('/foo', '/bar/baz')

    for _ in range(1000):
        dt = faker.date_time()
        bun = Bundle(timetag=TimeTag.from_datetime(dt))
        assert bun.timetag.to_datetime() == dt

        for addr in msg_addrs:
            msg = Message.create(addr, *arg_values)
            bun.add_packet(msg)

        bun_bytes = bun.build_packet()
        # print(f'bun_bytes={bun_bytes}')
        assert len(bun_bytes) % 4 == 0

        tt_bytes = bun_bytes[8:16]
        tt_val = struct.unpack('>Q', tt_bytes)[0]

        assert TimeTag.from_uint64(tt_val) == bun.timetag

        parsed, _ = Bundle.parse(bun_bytes)

        assert parsed.timetag == bun.timetag
        assert parsed.timetag.to_datetime() == dt

        for parsed_pkt, bun_pkt in zip(parsed, bun):
            check_parsed_message(bun_pkt, parsed_pkt)

def test_nested_bundles(message_addresses, random_arguments, faker):
    max_depth = 5
    messages_per_bundle = 3
    bundles_per_bundle = 5

    start_dt = faker.date_time()

    address_iter = iter(message_addresses)

    letters = 'abcdefghijkl'

    all_addresses = {}
    all_addresses_flat = set()
    all_bundles = {}
    all_bundle_dts = set()
    def create_bundle(parent=None, depth=0, parent_address=''):
        if parent is None:
            tt = TimeTag.from_datetime(start_dt)
        else:
            tt = TimeTag.from_float(parent.timetag.float_seconds + 1)

        bun = Bundle(timetag=tt)

        all_bundle_dts.add(bun.timetag.to_datetime())
        if depth not in all_addresses:
            all_addresses[depth] = []
        num_packets = 1

        for msg_ix in range(messages_per_bundle):
            args = [next(random_arguments) for _ in range(2)]
            msg = Message.create(f'{parent_address}/{letters[depth]}-{msg_ix}', *args)
            all_addresses[depth].append(msg.address.pattern)
            all_addresses_flat.add(msg.address.pattern)
            # print(msg.address.pattern)
            bun.add_packet(msg)
            num_packets += 1

        if depth < max_depth:
            for i in range(bundles_per_bundle):
                child, _num_packets = create_bundle(bun, depth+1, f'{parent_address}/{i}')
                bun.add_packet(child)
                num_packets += _num_packets

        return bun, num_packets

    root, total_packets = create_bundle()
    print(f'total_packets={total_packets}')
    # print(f'{all_addresses=}')
    bun_bytes = root.build_packet()

    print('data_len={}'.format(len(bun_bytes)))
    # print(bun_bytes)

    tt_bytes = bun_bytes[8:16]
    tt_val = struct.unpack('>Q', tt_bytes)[0]

    assert TimeTag.from_uint64(tt_val) == root.timetag

    parsed, remaining = Bundle.parse(bun_bytes)
    assert not len(remaining)

    all_parsed_addresses = {}
    all_parsed_addresses_flat = set()
    all_parsed_bundle_dts = set()

    def check_bundle(orig_bun, parsed_bun, depth=0):
        assert orig_bun.timetag == parsed_bun.timetag
        assert orig_bun.parent_index == parsed_bun.parent_index
        assert len(orig_bun) == len(parsed_bun)

        all_parsed_bundle_dts.add(parsed_bun.timetag.to_datetime())
        if depth not in all_parsed_addresses:
            all_parsed_addresses[depth] = []
        num_packets = 1

        for orig_pkt, parsed_pkt in zip(orig_bun, parsed_bun):
            assert isinstance(parsed_pkt, Packet)
            if isinstance(orig_pkt, Message):
                assert orig_pkt.address == parsed_pkt.address

                all_parsed_addresses[depth].append(parsed_pkt.address.pattern)
                all_parsed_addresses_flat.add(parsed_pkt.address.pattern)
                num_packets += 1
            else:
                num_packets += check_bundle(orig_pkt, parsed_pkt, depth+1)
        return num_packets

    total_parsed = check_bundle(root, parsed)
    assert total_parsed == total_packets
    assert all_addresses_flat == all_parsed_addresses_flat
    assert all_bundle_dts == all_parsed_bundle_dts
    assert all_addresses == all_parsed_addresses

    repacked = parsed.build_packet()
    assert repacked == bun_bytes


def test_random_addrs_and_args(message_addresses, random_arguments):
    args_per_message = 4
    messages_per_bundle = 8
    print('num_addresses: {}'.format(len(message_addresses)))
    bun = None
    for address in message_addresses:
        if bun is None:
            bun = Bundle()

        arg_values = [next(random_arguments) for _ in range(args_per_message)]
        msg = Message.create(address, *arg_values)
        bun.add_packet(msg)
        if len(bun) == messages_per_bundle:
            bun_bytes = bun.build_packet()

            parsed, remaining = Packet.parse(bun_bytes)
            # print(f'parsed={parsed}, remaining={remaining}')
            assert parsed.timetag == bun.timetag
            assert len(parsed) == len(bun)
            for parsed_pkt, bun_pkt in zip(parsed, bun):
                check_parsed_message(bun_pkt, parsed_pkt)

            bun = None

def test_invalid_packets():
    # properly formed message
    msg_bytes = b'/foo\x00\x00\x00\x00,i\x00\x00\x00\x00\x00\x01'

    # replace start message bytes with invalid data
    bad_msg_bytes = b'badmsg\x00\x00,i\x00\x00\x00\x00\x00\x01'

    # properly formed bundle
    bun_bytes = struct.pack('>8sQi16s', b'#bundle\x00', 1, len(msg_bytes), msg_bytes)

    # replace start bundle bytes with invalid data
    bad_bun_bytes = struct.pack('>8sQi16s', b'badbundl\x00', 1, len(msg_bytes), msg_bytes)

    # properly formed bundle containing invalid message
    bad_packed_msg_bytes = struct.pack('>8sQi16s', b'#bundle\x00', 1, len(bad_msg_bytes), bad_msg_bytes)


    # make sure valid packets parse properly
    good_msg, _ = Message.parse(msg_bytes)
    assert good_msg.address.pattern == '/foo'
    assert good_msg[0] == 1

    good_bundle, _ = Bundle.parse(bun_bytes)
    assert good_bundle.timetag == TimeTag.Immediately
    check_parsed_message(good_msg, good_bundle[0])

    # check bad message start exceptions
    with pytest.raises(PacketStartError):
        msg, _ = Packet.parse(bad_msg_bytes)

    with pytest.raises(MessageStartError):
        msg, _ = Message.parse(bad_msg_bytes)

    # check bad bundle start exceptions
    with pytest.raises(PacketStartError):
        bun, _ = Packet.parse(bad_bun_bytes)

    with pytest.raises(BundleStartError):
        bun, _ = Bundle.parse(bad_bun_bytes)

    # check bad message within packed bundle
    with pytest.raises(PacketStartError):
        bun, _ = Packet.parse(bad_packed_msg_bytes)

    with pytest.raises(PacketStartError):
        bun, _ = Bundle.parse(bad_packed_msg_bytes)
