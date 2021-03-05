import struct

from oscpython import ArgumentList, TimeTag
from oscpython import arguments


def test_random_args(random_arguments):
    num_args = 20
    num_iters = 20

    for i in range(num_iters):
        arg_list = ArgumentList()
        struct_fmts = []
        values = []
        for j in range(num_args):
            arg = next(random_arguments)
            arg_list.append(arg)
            struct_fmts.append(arg.get_struct_fmt())
            pack_value = arg.get_pack_value()
            if pack_value is not None:
                values.extend(list(pack_value))
        expected_fmt = '>{}'.format(''.join(struct_fmts))
        expected_len = struct.calcsize(expected_fmt)
        expected_bytes = struct.pack(expected_fmt, *values)
        assert arg_list.get_struct_fmt() == expected_fmt
        assert list(arg_list.values()) == values
        packed = arg_list.pack()
        assert packed == expected_bytes

def test_blob_of_args(random_arguments):
    num_args = 20
    num_iters = 20

    for i in range(num_iters):
        arg_list = ArgumentList()
        for j in range(num_args):
            arg = next(random_arguments)
            arg_list.append(arg)

        packed = arg_list.pack()

        # Repack the `packed` arg_list into a blob in another ArgumentList
        blob_list = ArgumentList([
            arguments.StringArgument('#bundle'),
            arguments.TimeTagArgument(TimeTag.Immediately),
        ])
        blob_list.append(arguments.BlobArgument(packed))
        blob_bytes = blob_list.pack()

        assert blob_bytes[:8] == b'#bundle\x00'
        assert int.from_bytes(blob_bytes[8:16], byteorder='big') == 1
        length_bytes = blob_bytes[16:20]
        assert len(packed).to_bytes(4, byteorder='big') == length_bytes

        parsed_length = struct.unpack('>i', length_bytes)[0]
        assert parsed_length == len(packed)

        payload_bytes = blob_bytes[20:parsed_length+20]
        assert payload_bytes == packed
