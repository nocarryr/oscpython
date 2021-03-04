from typing import Optional, ClassVar, Any, Union, List, Tuple, Iterable, Sequence
import enum
import dataclasses
from dataclasses import dataclass, field
import datetime
import struct

NTP_EPOCH = datetime.datetime(1900, 1, 1)
UNIX_EPOCH = datetime.datetime.utcfromtimestamp(0)

EPOCH_DIFF = UNIX_EPOCH - NTP_EPOCH
EPOCH_DIFF_SECONDS = EPOCH_DIFF.total_seconds()
TWO_TO_THE_32 = 2 ** 32
TWO_TO_THE_32_DIV = 1 / TWO_TO_THE_32

__all__ = (
    'get_padded_size', 'unpack_str_from_bytes', 'StructPacking', 'ArgumentList',
    'Client', 'TimeTag', 'ColorRGBA', 'Infinitum',
)

BytesOrString = Union[str, bytes]

def get_padded_size(s: BytesOrString, add_stop_byte: bool = True) -> int:
    length = len(s)
    if length % 4 == 0:
        if add_stop_byte:
            # add 4 bytes to ensure stop byte
            length += 4
        return length
    return (len(s) // 4 + 1) * 4

def unpack_str_from_bytes(b: bytes) -> Tuple[str, bytes]:
    stop_ix = b.index(b'\x00', 1)
    s = b[:stop_ix]
    psize = get_padded_size(s)
    b = b[psize:]
    return s.decode(), b

@dataclass
class StructPacking:
    """Helper for zipping struct format strings and values
    """
    value: Tuple[Any]
    format: str

class ArgumentList:
    """Container for :class:`~.arguments.Argument`
    """
    def __init__(self, initlist=None):
        if initlist is None:
            initlist = []
        else:
            initlist = initlist.copy()
        self.items: List['oscpython.arguments.Argument'] = initlist

    def append(self, item: 'oscpython.arguments.Argument'):
        """Add an :class:`~.arguments.Argument`
        """
        self.items.append(item)

    def extend(self, other):
        """Merge a sequence of :class:`~.arguments.Argument` instances or
        another :class:`ArgumentList`
        """
        if isinstance(other, ArgumentList):
            other = other.items
        self.items.extend(other)

    def __getitem__(self, key) -> 'oscpython.arguments.Argument':
        return self.items[key]

    def __setitem__(self, key, item: 'oscpython.arguments.Argument'):
        self.items[key] = item

    def __delitem__(self, key):
        del self.items[key]

    def get_struct_fmt(self) -> str:
        """Get the struct format string for all arguments in the list
        """
        f = tuple(self.formats())
        s = ''.join(f)
        return f'>{s}'

    def pack(self) -> bytes:
        """Pack all arguments in the list to binary using :func:`struct.pack`
        """
        fmt = self.get_struct_fmt()
        return struct.pack(fmt, *self.values())

    def formats(self) -> Iterable[str]:
        """Iterate over the format strings for each argument
        """
        for item in self:
            fmt = item.get_struct_fmt()
            if not len(fmt):
                continue
            yield fmt

    def values(self) -> Iterable[Any]:
        """Iterate (flattened) over all argument values
        (taken from :meth:`.arguments.Argument.get_pack_value`)
        """
        for item in self:
            value = item.get_pack_value()
            if value is None:
                continue
            yield from value

    def __iter__(self):
        yield from self.items

    def __repr__(self):
        return f'<{self.__class__}: {self}>'

    def __str__(self):
        return str(self.items)

@dataclass
class Client:
    """A network address and port
    """
    address: str    #: The host address
    port: int       #: The service port


@dataclass
class TimeTag:
    """An OSC timetag represented as two 32-bit integers (formatted as NTP)

    The values for :attr:`seconds` and :attr:`fraction` are relative to the
    NTP epoch (number of seconds since January 1, 1900).
    """
    seconds: int = 0
    """Whole number of seconds since the epoch"""

    fraction: int = 0
    """32-bit integer representing the fractional remainder of :attr:`seconds`
    """

    Immediately: ClassVar['TimeTag']
    """A constant used to send a special-case timetag meaning "immediately"
    """

    @property
    def is_immediate(self) -> bool:
        """Whether the special case of "immediately" is indicated
        """
        return self.seconds == 0 and self.fraction == 1

    @property
    def float_seconds(self) -> float:
        """The :attr:`seconds` and :attr:`fraction` combined into a :any:`float`
        """
        return self.seconds + (self.fraction * TWO_TO_THE_32_DIV)

    def to_epoch(self) -> float:
        """Return the values as a POSIX timestamp
        """
        return self.float_seconds - EPOCH_DIFF_SECONDS

    def to_datetime_utc(self) -> datetime.datetime:
        """Create a :class:`datetime.datetime` in UTC
        """
        return datetime.datetime.utcfromtimestamp(self.to_epoch())

    def to_datetime(self) -> datetime.datetime:
        """Create a :class:`datetime.datetime` with the local timezone offset

        Note:
            The returned datetime is naive (tzinfo=None)
        """
        return datetime.datetime.fromtimestamp(self.to_epoch())

    @classmethod
    def from_float(cls, value: float) -> 'TimeTag':
        """Create a :class:`TimeTag` from an NTP timestamp
        """
        seconds = int(value)
        fraction = (value - seconds) * TWO_TO_THE_32
        return cls(seconds=seconds, fraction=int(fraction))

    @classmethod
    def from_epoch(cls, seconds: float) -> 'TimeTag':
        """Create a :class:`TimeTag` from a POSIX timestamp
        """
        return cls.from_float(seconds + EPOCH_DIFF_SECONDS)

    @classmethod
    def from_datetime(cls, dt: datetime.datetime) -> 'TimeTag':
        """Create a :class:`TimeTag` from a :class:`datetime.datetime`

        The timezone behavior of the given datetime matches that of
        :meth:`datetime.datetime.timestamp`
        """
        return cls.from_epoch(dt.timestamp())

    @classmethod
    def from_uint64(cls, value: int) -> 'TimeTag':
        kw = {
            'seconds':value >> 32,
            'fraction':value & 0xFFFFFFFF,
        }
        return cls(**kw)
    def to_uint64(self) -> int:
        return (self.seconds << 32) + (self.fraction & 0xFFFFFFFF)

TimeTag.Immediately = TimeTag(seconds=0, fraction=1)

@dataclass
class ColorRGBA:
    """A 32-bit RGBA color with 8 bits per component
    """
    r: int = 0  #: Red component (0-255)
    g: int = 0  #: Green component (0-255)
    b: int = 0  #: Blue component (0-255)
    a: int = 0  #: Alpha component (0-255)
    @classmethod
    def from_uint64(cls, value: int) -> 'ColorRGBA':
        kw = {
            'r':(value >> 24) & 0xff,
            'g':(value >> 16) & 0xff,
            'b':(value >> 8) & 0xff,
            'a':value & 0xff,
        }
        return cls(**kw)
    def to_uint64(self) -> int:
        return (self.r << 24) + (self.g << 16) + (self.b << 8) + self.a

class Infinitum:
    """An OSC "Infinitum" argument, typically referred to as an "Impulse"

    There is no value for the argument as its presence in an OSC message
    provides the only semantic meaning.
    """
    def __eq__(self, other):
        return other is Infinitum or isinstance(other, Infinitum)
    def __ne__(self, other):
        return other is not Infinitum and not isinstance(other, Infinitum)
