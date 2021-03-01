import datetime

from oscpython import (
    Packet, Message, Bundle, TimeTag, ColorRGBA, Infinitum
)
from oscpython.common import get_padded_size

def test_message_arguments():
    now = datetime.datetime.utcnow()
    address = '/foo'
    arg_values = (
        1, 1.2, 'a string', b'a blob', True, False, None, Infinitum,
        ColorRGBA(99, 100, 101, 102), now,
    )
    typetags_expected = b',ifsbTFNIrt'
    typetags_length = get_padded_size(typetags_expected)
    typetags_expected = typetags_expected.ljust(typetags_length, b'\x00')

    msg = Message.create(address, *arg_values)
    msg_bytes = msg.build_packet()
    address_bytes = msg_bytes[:8]
    assert address_bytes[:len(address)].decode() == msg.address.pattern == address
    typetag_bytes = msg_bytes[8:typetags_length+8]
    assert typetag_bytes == typetags_expected
    all_arg_bytes = msg_bytes[typetags_length+8:]
    print(f'{all_arg_bytes=}')

    for arg in msg.arguments:
        try:
            bytes_expected = arg.build_packet()
        except ValueError as exc:
            if 'Cannot pack empty argument' in str(exc):
                continue
            raise
        arg_bytes = all_arg_bytes[:len(bytes_expected)]
        print(f'{arg=}: {bytes_expected=}, {arg_bytes=}')
        assert arg_bytes == bytes_expected
        all_arg_bytes = all_arg_bytes[len(bytes_expected):]
