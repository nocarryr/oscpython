from typing import Optional, ClassVar, Any, Union, List, Tuple, Sequence
import enum
import dataclasses
from dataclasses import dataclass, field
import datetime
import struct
import re

from oscpython.common import *
from oscpython.arguments import *
from oscpython.arguments import TimeTagArgument, StringArgument, BlobArgument

__all__ = (
    'ParseError', 'PacketStartError', 'MessageStartError', 'BundleStartError',
    'Address', 'Packet', 'Message', 'Bundle',
)

class ParseError(Exception):
    DEFAULT_MSG: ClassVar[Optional[str]] = None
    def __init__(self, packet_data: bytes, msg: Optional[str] = None):
        self.packet_data = packet_data
        if msg is None:
            msg = self.DEFAULT_MSG
        self.msg = msg
    def __str__(self):
        s = f'packet_data = "{self.packet_data!r}"'
        if self.msg is not None:
            s = f'{self.msg} ({s})'
        return s

class PacketStartError(ParseError):
    DEFAULT_MSG = 'Expected either "/" or "#" in start byte'

class MessageStartError(PacketStartError):
    DEFAULT_MSG = 'Expected "/" in start byte'

class BundleStartError(PacketStartError):
    DEFAULT_MSG = 'Expected "#bundle" in start bytes'

@dataclass
class TypeTags(StringArgument):
    """Container for OSC typetags
    """
    tags: List[str] = field(default_factory=list) #: The list of typetags

    def append(self, tag: str):
        """Append a typetag to the :attr:`tags` list
        """
        self.tags.append(tag)

    def get_pack_value(self) -> Optional[Tuple[bytes]]:
        if not len(self):
            return None
        return (',{}'.format(''.join(self.tags)).encode(),)

    @classmethod
    def parse(cls, data: bytes) -> Tuple['StringArgument', bytes]:
        s, remaining = unpack_str_from_bytes(data)
        assert s.startswith(',')
        tags = list(s.lstrip(','))
        return (cls(tags=tags), remaining)

    def __len__(self):
        return len(self.tags)

    def __iter__(self):
        yield from self.tags

class AddressPart:
    """One "part" of an :class:`Address` (delimited by forward slash)
    """

    __slots__ = ('__part', '__is_root', '__re_pattern', '__has_wildcard')
    def __init__(self,
                part: str,
                is_root: bool,
                re_pattern: Optional[re.Pattern] = None,
                has_wildcard: Optional[bool] = None):
        self.__part = part
        self.__is_root = is_root
        self.__re_pattern = re_pattern
        self.__has_wildcard = has_wildcard

    def __eq__(self, other):
        if not isinstance(other, AddressPart):
            return NotImplemented
        if self.part != other.part:
            return False
        if self.is_root != other.is_root:
            return False
        return True

    @property
    def part(self) -> str:
        """The address part as a string
        """
        return self.__part

    @property
    def is_root(self) -> bool:
        """True if this is the first part of the :class:`Address`
        """
        return self.__is_root

    @property
    def re_pattern(self) -> re.Pattern:
        """The address part as a compiled :class:`re.Pattern` to be used for
        OSC address pattern matching
        """
        p = self.__re_pattern
        if p is None:
            p, h = self.compile_re(self.part)
            self.__re_pattern, self.__has_wildcard = p, h
        return p

    @property
    def has_wildcard(self) -> bool:
        """True if the :attr:`re_pattern` contains any wildcard characters
        """
        h = self.__has_wildcard
        if h is None:
            p, h = self.compile_re(self.part)
            self.__re_pattern, self.__has_wildcard = p, h
        return h

    def match(self, other: 'AddressPart') -> bool:
        """Match this instance with another :class:`AddressPart` using
        OSC pattern matching
        """
        if not isinstance(other, AddressPart):
            return NotImplemented
        if self.has_wildcard:
            if not self.re_pattern.fullmatch(other.re_pattern.pattern):
                return False
        elif other.has_wildcard:
            m = other.re_pattern.fullmatch(self.re_pattern.pattern)
            if not m:
                return False
        else:
            return self.re_pattern.pattern == other.re_pattern.pattern
        return True


    @staticmethod
    def compile_re(pattern: str) -> Tuple[re.Pattern, bool]:
        """Create a regular expression used for OSC address pattern matching

        The pattern is only valid within the parts separated by forward slash
        (``"/"``)

        Returns
        -------
        pattern : re.Pattern
            The compiled pattern
        has_wildcard : bool
            ``True`` if the pattern contains any pattern-matching characters

        """
        # osc_style = [r'[a-d]', r'[!a-d]', r'{foo,bar}', r'a?c']
        # re_style = [r'[a-d]', r'[^a-d]', r'(foo|bar)', r'a\w?c']
        has_wildcard = False
        pattern = pattern.strip('/')
        if '*' in pattern:
            pattern = pattern.replace('*', r'[\w|\+]*')
            has_wildcard = True
        if '[' in pattern:
            has_wildcard = True
        if '[!' in pattern:
            pattern = pattern.replace('[!', '[^')
            has_wildcard = True
        for c, d in zip('{,}', '(|)'):
            if c in pattern:
                pattern = pattern.replace(c, d)
                has_wildcard = True
        if '?' in pattern:
            pattern = pattern.replace('?', r'\w?')
            has_wildcard = True
        return re.compile(pattern), has_wildcard

    def __repr__(self):
        return f'<{self.__class__}: "{self}">'

    def __str__(self):
        if self.is_root:
            return f'/{self.part}'
        return f'{self.part}'

@dataclass
class Address(StringArgument):
    """An OSC address pattern
    """
    pattern: str = '/' #: The OSC address string
    parts: Tuple[AddressPart] = field(default_factory=tuple, repr=False)
    """A :class:`tuple` of :class:`AddressPart` instances derived from the
    :attr:`pattern`, delimited by forward slash (``"/"``)
    """
    match_strings: ClassVar[str] = '?*[]{}'
    def __post_init__(self):
        if len(self.parts) and self.pattern == '/':
            self.pattern = self.parts_to_pattern(self.parts)
        elif self.pattern != '/':
            self.parts = self.pattern_to_parts(self.pattern)

    @staticmethod
    def parts_to_pattern(parts: Sequence[AddressPart]) -> str:
        """Convert the given :class:`parts <AddressPart>` to an OSC address
        string
        """
        # print(f'parts_to_pattern: {parts=}')
        if len(parts) == 1:
            pattern = parts[0].part
        else:
            pattern = '/'.join((part.part for part in parts))
        if parts[0].is_root:
            pattern = f'/{pattern}'
        return pattern

    @staticmethod
    def pattern_to_parts(pattern: str) -> Tuple[AddressPart]:
        """Convert the given OSC address string to a :class:`tuple`
        of :class:`parts <AddressPart>`
        """
        parts = []
        if '//' in pattern:
            pattern = pattern.split('//')[-1]
            for i, part in enumerate(pattern.split('/')):
                if not len(part):
                    continue
                if i == 0:
                    part = f'/{part}'
                parts.append(AddressPart(part=part, is_root=i == 0))#, index=i+1))
        else:
            is_root = pattern.startswith('/')
            for i, part in enumerate(pattern.lstrip('/').split('/')):
                if not len(part):
                    continue
                parts.append(AddressPart(part=part, is_root=is_root and i == 0))#, index=i))
        return tuple(parts)


    def get_pack_value(self) -> Optional[Tuple[bytes]]:
        return (self.pattern.encode(),)

    @property
    def is_concrete(self) -> bool:
        """True if the address is "concrete" (contains no pattern matching
        characters)
        """
        r = getattr(self, '_is_concrete', None)
        if r is not None:
            return r
        if '//' in self.pattern:
            r = False
        else:
            r = not any((c in self.pattern for c in self.match_strings))
        self._is_concrete = r
        return r

    @property
    def pattern_parts(self) -> Tuple[AddressPart]:
        return tuple((part.part for part in self.parts))

    @property
    def length(self) -> int:
        return len(self.parts)

    @classmethod
    def from_parts(cls, parts: Sequence[AddressPart]) -> 'Address':
        """Create an instance from the given sequence of :attr:`parts`
        """
        return cls(parts=tuple(parts))

    def __getitem__(self, key):
        if isinstance(key, slice):
            parts = self.parts[key]
            if key.start not in (0, None) and len(parts):
                parts = list(parts)
                p0 = parts[0]
                parts[0] = AddressPart(part=p0.part, is_root=False)
        else:
            parts = [self.parts[key]]
            if key > 0:
                p0 = parts[0]
                parts[0] = AddressPart(part=p0.part, is_root=False)
        return self.from_parts(parts)

    def __div__(self, other):
        return self.join(other)

    def __truediv__(self, other):
        return self.join(other)

    def __len__(self):
        # return len([p for p in self.parts if len(p)])
        return self.length

    def __iter__(self):
        yield from self.parts

    def join(self, other) -> 'Address':
        """Join the address with either a str or :class:`Address` instance,
        separating the :attr:`pattern` with ``"/"``
        """
        if not isinstance(other, (str, Address)):
            return NotImplemented
        if not isinstance(other, Address):
            other = Address(pattern=other)
        if '//' in other.pattern:
            raise ValueError('Cannot join with another "//" address')
        all_parts = list(self.parts)
        oth_parts = list(other.parts)
        # assert not oth_parts[0].is_root
        all_parts.extend(oth_parts)
        cls = self.__class__
        return cls.from_parts(all_parts)

    def match(self, other: Union['Address', str]) -> bool:
        """Match this address with another using pattern-matching rules

        Arguments:
            other: Either a :class:`str` or :class:`Address` instance

        Returns:
            bool: ``True`` if the given address matches
        """
        if not isinstance(other, Address):
            other = Address(pattern=other)
        if self.is_concrete and other.is_concrete:
            return self.pattern == other.pattern
        elif not self.is_concrete and not other.is_concrete:
            raise ValueError('At least one address must be concrete')

        # print(f'{self.pattern=}, {other.pattern=}')

        if '//' not in self.pattern and '//' not in other.pattern:
            if len(self) != len(other):
                return False
            for my_part, oth_part in zip(self, other):
                if not my_part.match(oth_part):
                    return False
            return True

        if '//' in self.pattern:
            wc_parts, parts = self.parts, other.parts
        elif '//' in other.pattern:
            wc_parts, parts = other.parts, self.parts
        i = 0
        for part in parts:
            try:
                wc_part = wc_parts[i]
            except IndexError:
                break
            if part.match(wc_part):
                i += 1

        return i == len(wc_parts)


@dataclass
class Packet:
    """OSC packet (either :class:`Message` or :class:`Bundle`)
    """

    remote_client: Optional[Client] = None
    """If the packet was received, the host that was received from. If sending
    the packet, the destination host
    """

    parent_bundle: Optional['Bundle'] = field(default=None, repr=False)
    """Instance of :class:`Bundle` that contains the packet (if any)
    """

    parent_index: Optional[int] = None
    """Index of the packet within the :attr:`parent_bundle`
    """

    @classmethod
    def parse(cls, packet_data: bytes) -> Tuple['Packet', bytes]:
        """Parse OSC-formatted bytes and build a :class:`Message` or :class:`Bundle`

        Returns a tuple of:
            :class:`Packet`
                The parsed object
            :class:`bytes`
                Any remaining bytes after the packet data
        """
        if packet_data.startswith(b'/'):
            return Message.parse(packet_data)
        elif packet_data.startswith(b'#bundle\x00'):
            return Bundle.parse(packet_data)
        else:
            raise MessageStartError(packet_data)

@dataclass
class Message(Packet):
    """An OSC Message
    """
    address: Address = field(default_factory=Address)
    """The OSC address pattern for the message
    """

    arguments: List[Argument] = field(default_factory=list)
    """OSC arguments for the message
    """

    @classmethod
    def create(cls, address: Union[Address, str], *args, **kwargs):
        """Convenience method to create a :class:`Message`

        Creates the :attr:`address` field from the provided address string
        and adds the message :attr:`arguments` contained in positional args
        """
        if not isinstance(address, Address):
            address = Address(pattern=address)
        kwargs['address'] = address
        msg = cls(**kwargs)
        msg.add_arguments(*args)
        return msg

    def add_argument(self, value: Any) -> Argument:
        """Create an :class:`~.arguments.Argument` from the given value
        and add it to the :attr:`arguments` list.

        If the value is an instance of :class:`~.arguments.Argument` it will
        be added without copying
        """
        ix = len(self)
        if isinstance(value, Argument):
            arg = value
            arg.index = ix
        else:
            arg_cls = Argument.get_argument_for_value(value)
            arg = arg_cls(value=value, index=ix)
        self.arguments.append(arg)
        return arg

    def add_arguments(self, *values):
        """Create multiple arguments using :meth:`add_argument`
        """
        for value in values:
            self.add_argument(value)

    def build_packet(self) -> bytes:
        """Construct a byte string for the message and its arguments
        """
        typetags = TypeTags()
        pack_list = ArgumentList([self.address, typetags])

        for arg in self:
            pack_list.append(arg)
            typetags.append(arg.tag)
        return pack_list.pack()

    @classmethod
    def parse(cls, packet_data: bytes) -> Tuple['Message', bytes]:
        if not packet_data.startswith(b'/'):
            raise MessageStartError(packet_data)
        address, packet_data = unpack_str_from_bytes(packet_data)
        args = []
        if packet_data.startswith(b','):
            typetags, packet_data = TypeTags.parse(packet_data)
            for tag in typetags:
                arg_cls = ARGUMENTS_BY_TAG[tag]
                arg, packet_data = arg_cls.parse(packet_data)
                args.append(arg)
        return (cls.create(address, *args), packet_data)

    def __iter__(self):
        yield from self.arguments

    def __len__(self):
        return len(self.arguments)

    def __getitem__(self, key):
        return self.arguments[key].value

@dataclass
class Bundle(Packet):
    """An OSC Bundle
    """
    timetag: TimeTag = TimeTag.Immediately
    """The :class:`~.common.TimeTag` associated with the bundle
    """

    packets: List[Packet] = field(default_factory=list)
    """List of :class:`Packet` instances to include in the bundle. Elements
    may be either :class:`Message` or :class:`Bundle` instances
    (nested bundles are allowed to occur)
    """

    def add_packet(self, packet: Packet):
        """Add a :class:`Message` or :class:`Bundle` to the :attr:`packets` list
        """
        ix = len(self)
        packet.parent_index = ix
        packet.parent_bundle = self
        self.packets.append(packet)

    def build_packet(self) -> bytes:
        """Construct a byte string for the bundle and the packets it contains
        """
        pack_list = ArgumentList([
            StringArgument(value='#bundle'),
            TimeTagArgument(value=self.timetag),
        ])

        for packet in self:
            _packet_data = packet.build_packet()
            pack_list.append(BlobArgument(_packet_data))
        return pack_list.pack()

    @classmethod
    def parse(cls, packet_data: bytes) -> Tuple['Bundle', bytes]:
        if not packet_data.startswith(b'#bundle\x00'):
            raise BundleStartError(packet_data)

        packet_data = packet_data[8:]
        tt, packet_data = TimeTagArgument.parse(packet_data)
        bun = cls(timetag=tt.value)

        while len(packet_data):
            length = struct.unpack('>i', packet_data[:4])[0]
            packet_data = packet_data[4:]
            if packet_data[0:1] not in (b'/', b'#'):
                raise PacketStartError(packet_data[:length])
            packet, remaining = Packet.parse(packet_data[:length])
            bun.add_packet(packet)
            packet_data = packet_data[length:]
            # assert remaining == packet_data

        return (bun, packet_data)

    def __iter__(self):
        yield from self.packets

    def __len__(self):
        return len(self.packets)

    def __getitem__(self, key):
        return self.packets[key]
