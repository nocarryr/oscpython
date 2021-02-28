from typing import Optional, ClassVar, Any, Union, List, Tuple
import enum
import dataclasses
from dataclasses import dataclass, field
import datetime

NTP_EPOCH = datetime.datetime(1900, 1, 1)
UNIX_EPOCH = datetime.datetime.utcfromtimestamp(0)
TZ_OFFSET = datetime.datetime.fromtimestamp(0) - UNIX_EPOCH

EPOCH_DIFF = UNIX_EPOCH - NTP_EPOCH
EPOCH_DIFF_SECONDS = EPOCH_DIFF.total_seconds()
TWO_TO_THE_32 = 2 ** 32
TWO_TO_THE_32_DIV = 1 / TWO_TO_THE_32

__all__ = (
    'get_padded_size', 'StructPacking', 'Client',
    'TimeTag', 'ColorRGBA', 'Infinitum',
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

@dataclass
class StructPacking:
    """Helper for zipping struct format strings and values
    """
    value: Any
    format: str

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
        return self.float_seconds + EPOCH_DIFF_SECONDS

    def to_datetime_utc(self) -> datetime.datetime:
        """Create a :class:`datetime.datetime` in UTC
        """
        return datetime.datetime.utcfromtimestamp(self.to_epoch())
    def to_datetime(self) -> datetime.datetime:
        """Create a :class:`datetime.datetime` with the local timezone offset

        Note:
            The returned datetime is naive (tzinfo=None)
        """
        dt = self.to_datetime_utc()
        return dt + TZ_OFFSET

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
        return cls.from_float(seconds - EPOCH_DIFF_SECONDS)

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
            'fraction':value % 0xFFFFFFFF,
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
