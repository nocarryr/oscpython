import array
import struct
import string
import pytest
import datetime

from oscpython import arguments, ColorRGBA, Infinitum, TimeTag


INT32_MAX = (1 << 31) - 1
INT32_MIN = (1 << 31) * -1

INT64_MAX = (1 << 63) - 1
INT64_MIN = (1 << 63) * -1

FLOAT32_EXP_BITS = 8
FLOAT32_FRAC_BITS = 23
FLOAT64_EXP_BITS = 11
FLOAT64_FRAC_BITS = 52


def iter_int_values(int_min, int_max):
    i = 0
    while i < int_max:
        for j in range(128):
            k = i + j
            if k > int_max:
                break
            yield k
            yield -k
        if i == 0:
            i = 1
        else:
            i = i << 1
    yield int_min
    yield int_max

def iter_float_values(typecode, exp_bits, frac_bits):
    exp = (1 << exp_bits) - 1
    frac = 1 / ((1 << frac_bits) - 1)
    a = array.array(typecode, [0, 0])
    for i in range(exp):
        for j in range(frac_bits):
            k = (1 << j) * frac
            k += i
            a[0] = k
            a[1] = -k
            yield a[0]
            yield a[1]

def check_arg_packet(arg, struct_fmt, allow_padding=False):
    arg_bytes = arg.build_packet()
    arg_byte_len = len(arg_bytes)
    assert arg_byte_len % 4 == 0
    if allow_padding:
        struct_calc_len = struct.calcsize(struct_fmt)
        if arg_byte_len > struct_calc_len:
            diff = arg_byte_len - struct_calc_len
            # struct_fmt = ''.join([struct_fmt, []])
            struct_fmt = f'{struct_fmt}{diff}x'
    unpacked = struct.unpack(struct_fmt, arg_bytes)[0]
    assert unpacked == arg.get_pack_value()[0]
    return arg_bytes

def test_int_args():
    int32_fmt = '>i'
    int64_fmt = '>q'
    for i in iter_int_values(INT32_MIN, INT32_MAX):
        cls = arguments.Argument.get_argument_for_value(i)
        assert cls is arguments.Int32Argument
        arg = cls(value=i)
        check_arg_packet(arg, int32_fmt)
        parsed, _ = cls.parse(arg.build_packet())
        assert parsed == arg

    for i in iter_int_values(INT64_MIN, INT64_MAX):
        if i == 0:
            continue
        elif i < 0 and i >= INT32_MIN:
            i += INT32_MIN
        elif i > 0 and i <= INT32_MAX:
            i += INT32_MAX
        cls = arguments.Argument.get_argument_for_value(i)
        if cls is not arguments.Int64Argument:
            print(i)
        assert cls is arguments.Int64Argument
        arg = cls(value=i)
        check_arg_packet(arg, int64_fmt)
        parsed, _ = cls.parse(arg.build_packet())
        assert parsed == arg

def test_float_args():
    float32_fmt = '>f'
    float64_fmt = '>d'

    for f in iter_float_values('f', FLOAT32_EXP_BITS, FLOAT32_FRAC_BITS):
        if f == 0:
            cls = arguments.Float32Argument
        else:
            cls = arguments.Argument.get_argument_for_value(f)
            assert cls is arguments.Float32Argument
        arg = cls(value=f)
        check_arg_packet(arg, float32_fmt)
        parsed, _ = cls.parse(arg.build_packet())
        assert parsed == arg

    for f in iter_float_values('d', FLOAT64_EXP_BITS, FLOAT64_FRAC_BITS):
        arg = arguments.Float64Argument(value=f)
        check_arg_packet(arg, float64_fmt)
        parsed, _ = arguments.Float64Argument.parse(arg.build_packet())
        assert parsed == arg

def test_string_args():
    def iter_chars():
        while True:
            yield from string.printable
    def get_strings(count, length):
        it = iter_chars()
        for i in range(count):
            r = []
            for j in range(length):
                r.append(next(it))
            yield ''.join(r)

    for length in range(1, 30):
        for s in get_strings(20, length):

            # StringArgument
            cls = arguments.Argument.get_argument_for_value(s)
            assert cls is arguments.StringArgument
            arg = cls(value=s)
            check_arg_packet(arg, f'>{length}s', allow_padding=True)
            parsed, _ = cls.parse(arg.build_packet())
            assert parsed == arg


            #BlobArgument
            b = s.encode()
            cls = arguments.Argument.get_argument_for_value(b)
            assert cls is arguments.BlobArgument
            arg = cls(value=b)

            struct_fmt = f'>i{length}s'
            arg_bytes = arg.build_packet()
            arg_byte_len = len(arg_bytes)
            assert arg_byte_len % 4 == 0

            struct_calc_len = struct.calcsize(struct_fmt)
            if arg_byte_len > struct_calc_len:
                diff = arg_byte_len - struct_calc_len
                struct_fmt = f'{struct_fmt}{diff}x'
            unpacked_count, unpacked_bytes = struct.unpack(struct_fmt, arg_bytes)
            assert unpacked_count == len(arg.value)
            assert unpacked_bytes == arg.value

            parsed, _ = cls.parse(arg.build_packet())
            assert parsed == arg

def test_const_args():
    const_map = [
        (True, arguments.TrueArgument),
        (False, arguments.FalseArgument),
        (None, arguments.NilArgument),
        (Infinitum(), arguments.InfinitumArgument),
    ]
    for value, argcls in const_map:
        cls = arguments.Argument.get_argument_for_value(value)
        assert cls is argcls
        arg = cls(value=value)
        with pytest.raises(ValueError) as excinfo:
            arg.build_packet()
        assert 'Cannot pack empty argument' in str(excinfo.value)

def test_color_args():
    for r, g, b, a in zip(range(255), range(255), range(255), range(255)):
        color = ColorRGBA(r=r, g=g, b=b, a=a)
        cls = arguments.Argument.get_argument_for_value(color)
        assert cls is arguments.RGBArgument
        arg = cls(value=color)
        arg_bytes = check_arg_packet(arg, '>q')
        unpacked = struct.unpack('>q', arg_bytes)[0]
        unpacked_color = ColorRGBA.from_uint64(unpacked)
        assert unpacked_color == color

        parsed, _ = cls.parse(arg.build_packet())
        assert parsed == arg

def test_timestamp_args():
    now_dt = datetime.datetime.utcnow()
    for second in range(59):
        for microsecond in range(100):
            now_dt = now_dt.replace(second=second, microsecond=microsecond)
            now_tt = TimeTag.from_datetime(now_dt)
            assert now_dt == now_tt.to_datetime()

            cls = arguments.Argument.get_argument_for_value(now_dt)
            assert cls is arguments.TimeTagArgument

            cls = arguments.Argument.get_argument_for_value(now_tt)
            assert cls is arguments.TimeTagArgument

            arg_dt = cls(value=now_dt)
            arg_bytes = arg_dt.build_packet()
            assert len(arg_bytes) % 4 == 0
            unpacked_dt = struct.unpack('>Q', arg_bytes)[0]
            tt1 = TimeTag.from_uint64(unpacked_dt)

            arg_tt = cls(value=now_tt)
            arg_bytes = arg_tt.build_packet()
            assert len(arg_bytes) % 4 == 0
            unpacked_tt = struct.unpack('>Q', arg_bytes)[0]
            tt2 = TimeTag.from_uint64(unpacked_tt)

            assert tt1 == tt2
            assert arg_dt.get_pack_value() == arg_tt.get_pack_value()

            parsed_dt, _ = cls.parse(arg_dt.build_packet())
            parsed_tt, _ = cls.parse(arg_tt.build_packet())

            assert parsed_tt.get_pack_value() == arg_tt.get_pack_value()
            assert parsed_dt.get_pack_value() == arg_dt.get_pack_value()
