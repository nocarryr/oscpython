from typing import Optional, ClassVar, Any, Union, Tuple, Sequence
import enum
import dataclasses
from dataclasses import dataclass, field
import datetime
import struct


from oscpython.common import *

__all__ = (
    'ArgumentError', 'ArgumentTypeError', 'ArgumentValueError',
    'Argument', 'ARGUMENTS', 'ARGUMENTS_BY_TAG',
)

UINT32_MAX = (1 << 32) - 1

INT32_MAX = (1 << 31) - 1
INT32_MIN = (1 << 31) * -1

INT64_MAX = (1 << 63) - 1
INT64_MIN = (1 << 63) * -1


class ArgumentError(Exception):
    msg: Optional[str]
    def __init__(self, value: Any, msg: Optional[str] = None):
        self.value = value
        self.msg = msg
    def __str__(self):
        s = f'value = "{self.value!r}"'
        if self.msg is not None:
            s = f'{self.msg} ({s})'
        return s

class ArgumentTypeError(ArgumentError):
    pass

class ArgumentValueError(ArgumentError):
    pass


@dataclass
class Argument:
    """Base class for OSC arguments
    """
    tag: ClassVar[str]          #: The OSC type tag for the argument
    struct_fmt: ClassVar[str]   #: Format string used by :mod:`struct`
    py_type: ClassVar[type]     #: The matching Python type for the argument
    value: Optional[Any] = None #: The argument value
    index: int = -1             #: The argument index within its parent :class:`oscpython.messages.Message`

    @classmethod
    def get_argument_for_value(cls, value: Any) -> 'Argument':
        """Get an :class:`Argument` subclass to handle the given value

        Raises:
            ArgumentTypeError: If the given type is not supported
        """
        if value is True:
            return TrueArgument
        elif value is False:
            return FalseArgument
        elif value is None:
            return NilArgument
        elif value == Infinitum:
            return InfinitumArgument

        tp = type(value)
        if tp not in ARGUMENTS_BY_TYPE:
            raise ArgumentTypeError(value, 'Unknown Type')

        arg_classes = ARGUMENTS_BY_TYPE[tp]
        for arg_cls in arg_classes.values():
            if arg_cls.works_for_value(value):
                return arg_cls
        raise ArgumentTypeError(value)

    def __post_init__(self):
        self.validate_value()

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        """Return ``True`` if the class is able to handle the given value
        and its type
        """
        raise NotImplementedError

    def validate_value(self):
        """Perform value checks (used by subclasses)

        Raises:
            ArgumentValueError: If the :attr:`value` is invalid
        """
        pass

    def get_struct_fmt(self) -> str:
        """Return the format string for :func:`struct.pack` matching the current
        :attr:`value`

        This should normally be :attr:`struct_fmt`, but certain types (like str)
        must be able to override with the appropriate length
        """
        return self.struct_fmt

    def pack(self) -> StructPacking:
        """Create a :class:`~.common.StructPacking` for the argument
        """
        value = self.get_pack_value()
        return StructPacking(value=value, format=self.get_struct_fmt())

    def build_packet(self) -> bytes:
        """Pack the argument to bytes formatted for an OSC packet
        """
        packing = self.pack()
        if not len(packing.format):
            raise ValueError('Cannot pack empty argument')
        return struct.pack(f'>{packing.format}', *packing.value)

    def get_pack_value(self) -> Optional[Tuple[Any]]:
        """Get the value(s) to be packed using :func:`struct.pack`

        Returns ``None`` if no value is associated with the argument,
        otherwise a tuple (even if there is only one item)
        """
        return (self.value,)

    @classmethod
    def parse(cls, data: bytes) -> Tuple['Argument', bytes]:
        """Parse OSC-formatted data and create an :class:`Argument`

        Returns a tuple of:
            :class:`Argument`
                Argument containing the parsed :attr:`value`
            :class:`bytes`
                Any remaining bytes after the argument data
        """
        kw = {}
        if len(cls.struct_fmt):
            fmt = f'>{cls.struct_fmt}'
            length = struct.calcsize(fmt)
            _data = data[:length]
            data = data[length:]
            value = struct.unpack(fmt, _data)
            if len(value) == 1:
                value = value[0]
            kw['value'] = cls._transform_parsed_value(value)
        return (cls(**kw), data)

    @classmethod
    def _transform_parsed_value(cls, value: Any) -> Any:
        return value

@dataclass
class Int32Argument(Argument):
    """16-bit integer argument
    """
    tag: ClassVar[str] = 'i'
    struct_fmt: ClassVar[str] = 'i'
    py_type: ClassVar[type] = int

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        if not isinstance(value, int):
            return False
        return INT32_MIN <= value <= INT32_MAX

    def validate_value(self):
        if INT32_MIN <= self.value <= INT32_MAX:
            return
        raise ArgumentValueError(self.value, f'Must be {INT32_MIN} <= value <= {INT32_MAX}')

@dataclass
class Float32Argument(Argument):
    """32-bit float argument
    """
    tag: ClassVar[str] = 'f'
    struct_fmt: ClassVar[str] = 'f'
    py_type: ClassVar[type] = float

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return isinstance(value, (int, float))

@dataclass
class StringArgument(Argument):
    """String argument
    """
    tag: ClassVar[str] = 's'
    struct_fmt: ClassVar[str] = ''
    py_type: ClassVar[type] = str

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return isinstance(value, str)

    def get_pack_value(self) -> Optional[Tuple[str]]:
        if not len(self.value):
            return None
        return (self.value.encode(),)

    def get_struct_fmt(self) -> str:
        value = self.get_pack_value()
        if value is None:
            return ''
        length = get_padded_size(value[0], add_stop_byte=True)
        return f'{length}s'

    @classmethod
    def parse(cls, data: bytes) -> Tuple['StringArgument', bytes]:
        s, remaining = unpack_str_from_bytes(data)
        value = cls._transform_parsed_value(s)
        return (cls(value=s), remaining)


@dataclass
class BlobArgument(Argument):
    """Blob (:class:`bytes`) argument
    """
    tag: ClassVar[str] = 'b'
    struct_fmt: ClassVar[str] = ''
    py_type: ClassVar[type] = bytes

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return isinstance(value, bytes)

    def validate_value(self):
        # it would be interesting if this ever evaluated as True
        # ( the blob would use > 4GB of memory )
        if len(self.value) > UINT32_MAX: # pragma: no cover
            raise ArgumentValueError(self.value, f'Blob length must be <= {UINT32_MAX}')

    def get_pack_value(self) -> Optional[Tuple[int, bytes]]:
        return (len(self.value), self.value)

    def get_struct_fmt(self) -> str:
        count, value = self.get_pack_value()
        count_bytes = b'\x00\x00\x00\x00'
        value = b''.join([count_bytes, value])
        length = get_padded_size(value, add_stop_byte=False)
        length -= 4
        return f'i{length}s'

    @classmethod
    def parse(cls, data: bytes) -> Tuple['BlobArgument', bytes]:
        length = struct.unpack('>i', data[:4])[0]
        padded_length = get_padded_size(data[:length+4], add_stop_byte=False)
        value = struct.unpack(f'>{length}s', data[4:length+4])
        if len(value) == 1:
            value = value[0]
        value = cls._transform_parsed_value(value)
        remaining = data[padded_length:]
        return (cls(value=value), remaining)

@dataclass
class Int64Argument(Int32Argument):
    """64-bit integer argument
    """
    tag: ClassVar[str] = 'h'
    struct_fmt: ClassVar[str] = 'q'

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        if not isinstance(value, int):
            return False
        return INT64_MIN <= value <= INT64_MAX

    def validate_value(self):
        if INT64_MIN <= self.value <= INT64_MAX:
            return
        raise ArgumentValueError(self.value, f'Must be {INT64_MIN} <= value <= {INT64_MAX}')

@dataclass
class TimeTagArgument(Argument):
    """TimeTag argument (see :class:`~.common.TimeTag`)
    """
    tag: ClassVar[str] = 't'
    struct_fmt: ClassVar[str] = 'Q'
    py_type: ClassVar[type] = TimeTag

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return isinstance(value, (TimeTag, datetime.datetime))

    def get_pack_value(self) -> Optional[Tuple[int]]:
        value = self.value
        if isinstance(value, datetime.datetime):
            value = TimeTag.from_datetime(value)
        return (value.to_uint64(),)

    @classmethod
    def _transform_parsed_value(cls, value: int) -> TimeTag:
        return TimeTag.from_uint64(value)

@dataclass
class Float64Argument(Float32Argument):
    """64-bit float argument
    """
    tag: ClassVar[str] = 'd'
    struct_fmt: ClassVar[str] = 'd'

@dataclass
class CharArgument(Argument):
    """Char argument (a single ascii character)
    """
    tag: ClassVar[str] = 'c'
    struct_fmt: ClassVar[str] = 'sxxx'
    py_type: ClassVar[type] = str

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return len(value) == 1

    def get_pack_value(self) -> Optional[Tuple[bytes]]:
        return (self.value.encode(),)

    def validate_value(self):
        if len(self.value) != 1:
            raise ArgumentValueError(self.value, 'Must be a single character')

    @classmethod
    def _transform_parsed_value(cls, value: bytes) -> str:
        return value[:1].decode()

@dataclass
class RGBArgument(Argument):
    """RGBA color argument (see :class:`~.common.ColorRGBA`)
    """
    tag: ClassVar[str] = 'r'
    struct_fmt: ClassVar[str] = 'q'
    py_type: ClassVar[type] = ColorRGBA

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return isinstance(value, ColorRGBA)

    def get_pack_value(self) -> Optional[Tuple[int]]:
        return (self.value.to_uint64(),)

    @classmethod
    def _transform_parsed_value(cls, value: int) -> ColorRGBA:
        return ColorRGBA.from_uint64(value)


@dataclass
class MidiArgument(Argument):
    """A 4-byte MIDI message
    """
    tag: ClassVar[str] = 'm'
    struct_fmt: ClassVar[str] = '4B'
    py_type: ClassVar[type] = MidiMessage

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return isinstance(value, MidiMessage)

    def get_pack_value(self) -> Optional[Tuple[int]]:
        return self.value.as_tuple()

    @classmethod
    def _transform_parsed_value(cls, value: Sequence[int]) -> MidiMessage:
        return MidiMessage.from_iterable(value)

@dataclass
class BoolArgument(Argument):
    struct_fmt: ClassVar[str] = ''
    py_type: ClassVar[type] = bool

    def get_pack_value(self) -> Optional[Tuple[Any]]:
        return None

@dataclass
class TrueArgument(BoolArgument):
    """Argument for ``True``
    """
    tag: ClassVar[str] = 'T'
    struct_fmt: ClassVar[str] = ''
    value: Optional[Any] = True

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return value is True

@dataclass
class FalseArgument(BoolArgument):
    """Argument for ``False``
    """
    tag: ClassVar[str] = 'F'
    struct_fmt: ClassVar[str] = ''
    value: Optional[Any] = False

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return value is False

@dataclass
class NilArgument(Argument):
    """Nil (``None``) argument
    """
    tag: ClassVar[str] = 'N'
    struct_fmt: ClassVar[str] = ''
    py_type: ClassVar[type] = type(None)
    value: Optional[Any] = None

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return value is None

    def get_pack_value(self) -> Optional[Tuple[Any]]:
        return None

@dataclass
class InfinitumArgument(Argument):
    """Infinitum argument (see :class:`~.common.Infinitum`)
    """
    tag: ClassVar[str] = 'I'
    struct_fmt: ClassVar[str] = ''
    py_type: ClassVar[type] = Infinitum
    value: Optional[Any] = field(default_factory=Infinitum)

    @classmethod
    def works_for_value(cls, value: Any) -> bool:
        return True

    def get_pack_value(self) -> Optional[Tuple[Any]]:
        return None

ARGUMENTS = (
    Int32Argument, Float32Argument, StringArgument, BlobArgument, Int64Argument,
    TimeTagArgument, Float64Argument, CharArgument, RGBArgument, TrueArgument,
    FalseArgument, NilArgument, InfinitumArgument, MidiArgument,
)

ARGUMENTS_BY_TAG = {_cls.tag:_cls for _cls in ARGUMENTS}
ARGUMENTS_BY_TYPE = {}
for _cls in ARGUMENTS:
    if _cls.py_type not in ARGUMENTS_BY_TYPE:
        ARGUMENTS_BY_TYPE[_cls.py_type] = {}
    ARGUMENTS_BY_TYPE[_cls.py_type][_cls.__name__] = _cls
ARGUMENTS_BY_TYPE[datetime.datetime] = {TimeTagArgument.__name__:TimeTagArgument}
