import datetime
import pytest

from oscpython import (
    Packet, Message, Bundle, TimeTag, ColorRGBA, Infinitum
)

@pytest.fixture
def message_args():
    now = datetime.datetime.utcnow()
    arg_values = (
        1, 1.2, 'a string', b'a blob', True, False, None, Infinitum,
        ColorRGBA(99, 100, 101, 102), now,
    )
    typetags_expected = b',ifsbTFNIrt\x00'
    return arg_values, typetags_expected

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
