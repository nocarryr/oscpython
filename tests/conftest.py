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

@pytest.fixture
def message_addresses(faker):
    n_levels = 7
    n_branches = 3

    def build(parent=None, depth=0):
        parts = faker.words(n_branches)
        for part in parts:
            if parent is None:
                address = f'/{part}'
            else:
                address = '/'.join([parent, part])
            yield address
            if depth < n_levels:
                yield from build(address, depth+1)
    return (tuple(build()))

@pytest.fixture
def random_arguments(faker):
    arg_tags = list(arguments.ARGUMENTS_BY_TAG.keys())
    num_tags = len(arg_tags)
    def gen_args():
        while True:
            tag_ix = faker.pyint(max_value=num_tags-1)
            arg_cls = arguments.ARGUMENTS_BY_TAG[arg_tags[tag_ix]]
            if arg_cls.tag in ['T', 'F', 'N', 'I']:
                yield arg_cls()
                continue
            if arg_cls is arguments.Int32Argument:
                value = faker.pyint(min_value=arguments.INT32_MIN, max_value=arguments.INT32_MAX)
            elif arg_cls is arguments.Int64Argument:
                value = faker.pyint(min_value=arguments.INT64_MIN, max_value=arguments.INT64_MAX)
            elif arg_cls.py_type is float:
                value = faker.pyfloat()
            elif arg_cls is arguments.StringArgument:
                value = faker.sentence()
            elif arg_cls is arguments.CharArgument:
                continue
                value = faker.pystr(max_chars=1)
            elif arg_cls is arguments.BlobArgument:
                length = faker.pyint(min_value=1, max_value=255)
                value = faker.binary(length=length)
            elif arg_cls is arguments.TimeTagArgument:
                value = faker.date_time()
            elif arg_cls is arguments.RGBArgument:
                rgba = {k:faker.pyint(max_value=255) for k in ['r','g','b','a']}
                value = ColorRGBA(**rgba)
            yield arg_cls(value=value)
    return gen_args()
