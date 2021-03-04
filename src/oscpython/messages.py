from typing import Optional, ClassVar, Any, Union, List, Tuple
import enum
import dataclasses
from dataclasses import dataclass, field
import datetime
import struct

from oscpython.common import *
from oscpython.arguments import *
from oscpython.arguments import TimeTagArgument, StringArgument

__all__ = ('Address', 'Packet', 'Message', 'Bundle')

class ParseError(Exception):
    def __init__(self, packet_data: bytes):
        self.packet_data = packet_data
    def __str__(self):
        return f'Could not parse data: {self.packet_data}'

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

@dataclass
class Address(StringArgument):
    """An OSC address pattern
    """
    pattern: str = '/'
    def get_pack_value(self) -> Optional[Tuple[bytes]]:
        return (self.pattern.encode(),)

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
            raise ParseError(packet_data)

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
        ix = len(self.arguments)
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
        all_packs = [self.address.pack()]
        packs = []
        typetags = TypeTags()
        for arg in self.arguments:
            typetags.append(arg.tag)
            pack = arg.pack()
            if len(pack.format):
                packs.append(pack)
        if len(typetags):
            all_packs.append(typetags.pack())
        if len(packs):
            all_packs.extend(packs)

        struct_fmt = '>{}'.format(''.join([pack.format for pack in all_packs]))
        struct_args = [v for pack in all_packs for v in pack.value]
        return struct.pack(struct_fmt, *struct_args)

    @classmethod
    def parse(cls, packet_data: bytes) -> Tuple['Message', bytes]:
        if not packet_data.startswith(b'/'):
            raise ParseError(packet_data)
        address, packet_data = unpack_str_from_bytes(packet_data)
        args = []
        if packet_data.startswith(b','):
            typetags, packet_data = TypeTags.parse(packet_data)
            for tag in typetags:
                arg_cls = ARGUMENTS_BY_TAG[tag]
                arg, packet_data = arg_cls.parse(packet_data)
                args.append(arg)
        return (cls.create(address, *args), packet_data)

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
        ix = len(self.packets)
        packet.parent_index = ix
        packet.parent_bundle = self
        self.packets.append(packet)

    def build_packet(self) -> bytes:
        """Construct a byte string for the bundle and the packets it contains
        """
        tt = TimeTagArgument(value=self.timetag)

        packet_data = [
            b'#bundle\x00',
            tt.build_packet(),
        ]

        for packet in self.packets:
            _packet_data = packet.build_packet()
            packet_data.append(struct.pack('>i', len(_packet_data)))
            packet_data.append(_packet_data)
        return b''.join(packet_data)

    @classmethod
    def parse(cls, packet_data: bytes) -> Tuple['Bundle', bytes]:
        if not packet_data.startswith(b'#bundle\x00'):
            raise ParseError(packet_data)

        packet_data = packet_data[8:]
        tt, packet_data = TimeTagArgument.parse(packet_data)
        bun = cls(timetag=tt.value)

        while len(packet_data):
            length = struct.unpack('>i', packet_data[:4])[0]
            packet_data = packet_data[4:]
            if packet_data[0:1] not in (b'/', b'#'):
                break
            packet, remaining = Packet.parse(packet_data)
            bun.add_packet(packet)
            packet_data = packet_data[length:]
            # assert remaining == packet_data

        return (bun, packet_data)
