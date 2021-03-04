import datetime
import struct
import pytest

from oscpython import (
    Packet, Message, Bundle, TimeTag, ColorRGBA, Infinitum
)
from oscpython import arguments

@pytest.fixture
def message_args():
    now = datetime.datetime.utcnow()
    arg_values = (
        1, 1.2, 'a string', b'a blob', True, False, None, Infinitum,
        ColorRGBA(99, 100, 101, 102), now,
    )
    typetags_expected = b',ifsbTFNIrt\x00'
    return arg_values, typetags_expected

def check_message_args(msg: Message, all_arg_bytes: bytes):
    for arg in msg.arguments:
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
    assert len(parsed_msg.arguments) == len(expected_msg.arguments)
    for parg, marg in zip(parsed_msg.arguments, expected_msg.arguments):
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

    for i, msg in enumerate(messages):
        assert msg.parent_bundle is bun
        assert msg.parent_index == i

    bun_bytes = bun.build_packet()
    print(f'bun_bytes={bun_bytes}')
    assert len(bun_bytes) % 4 == 0
    assert bun_bytes.startswith(b'#bundle\x00')

    tt_bytes = bun_bytes[8:16]
    tt_val = struct.unpack('>q', tt_bytes)[0]
    assert TimeTag.from_uint64(tt_val) == bun.timetag == TimeTag.Immediately
    assert tt_val == 1

    payload_bytes = bun_bytes[16:]
    all_msg_bytes = []

    while len(payload_bytes):
        msg_size = struct.unpack('>i', payload_bytes[:4])[0]
        print(f'msg_size={msg_size}')
        payload_bytes = payload_bytes[4:]
        msg_bytes = payload_bytes[:msg_size]
        payload_bytes = payload_bytes[msg_size:]
        all_msg_bytes.append(msg_bytes)

    assert len(all_msg_bytes) == len(messages)

    for msg, addr, msg_bytes in zip(messages, msg_addrs, all_msg_bytes):
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

        assert msg.build_packet() == msg_bytes

    parsed, remaining = Packet.parse(bun_bytes)
    print(f'parsed={parsed}, remaining={remaining}')
    assert parsed.timetag == bun.timetag
    assert len(parsed.packets) == len(bun.packets)
    for parsed_pkt, bun_pkt in zip(parsed.packets, bun.packets):
        check_parsed_message(bun_pkt, parsed_pkt)
