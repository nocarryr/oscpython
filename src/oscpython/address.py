from typing import (
    Optional, Sequence, List, Dict, Tuple, Union, Iterator, Any,
    KeysView, ValuesView, ItemsView, ClassVar, Callable,
)
from dataclasses import dataclass, field
import re

from pydispatch import Dispatcher
from pydispatch.dispatch import Event

from oscpython.arguments import StringArgument

messages, Message, Bundle = None, None, None
def _import_message_classes():
    global messages, Message, Bundle
    if messages is not None:
        return
    from oscpython import messages as _msg_module
    messages = _msg_module
    Message = _msg_module.Message
    Bundle = _msg_module.Bundle


StrOrAddress = Union[str, 'Address']

__all__ = ('Address', 'AddressPart', 'AddressSpace', 'AddressNode')


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

    def copy(self) -> 'Address':
        """Create a copy of the instance
        """
        cls = self.__class__
        return cls.from_parts(self.parts)

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


class AddressSpace(Dispatcher):
    """An OSC address space, container for root (top-level)
    :class:`AddressNode` instances

    Attributes:
        root_nodes: Mapping of root nodes using the :attr:`~AddressNode.name`
            as keys

    :Events:

        .. event:: on_message(address: Address, message: Message, timetag: TimeTag)

            Fired when a message is received by a :class:`server <.transport.BaseServer>`.

            :param address: The OSC address matching the message
            :type address: oscpython.address.Address
            :param message: The OSC message
            :type message: oscpython.messages.Message
            :param timetag: The timestamp of when the message was received
            :type timetag: oscpython.common.TimeTag

    """

    root_nodes: Dict[str, 'AddressNode']

    _events_ = ['on_message']

    def __init__(self):
        self.root_nodes = {}

    def add_root(self, name: str, cls: Optional[type] = None) -> 'AddressNode':
        """Create an :class:`AddressNode` and add it to :attr:`root_nodes`

        Arguments:
            name (str): The node :attr:`~AddressNode.name`
            cls (optional): A subclass of :class:`AddressNode` to use when
                creating the root node. If not provided,
                defaults to :class:`AddressNode`
        """
        if cls is None:
            cls = AddressNode
        if name in self:
            obj = self[name]
            if obj.__class__ is not cls:
                raise KeyError(f'Node with name "{name}" already exists')
            return obj

        obj = cls(name)
        obj.address_space = self
        self.root_nodes[name] = obj
        return obj

    def add_root_instance(self, node: 'AddressNode'):
        """Add an existing :class:`AddressNode` instance to :attr:`root_nodes`

        Arguments:
            node: The instance to add
        """
        if node.name in self:
            raise KeyError(f'Node with name "{node.name}" already exists')
        node.parent = None
        self.root_nodes[node.name] = node
        node.address_space = self

    def create_from_address(self, address: StrOrAddress, cls: Optional[type] = None) -> 'AddressNode':
        """Create node or nodes from the given OSC address and return the
        final node on the tree

        Arguments:
            address: The OSC address
            cls: If provided, a subclass of :class:`AddressNode` to use when
                creating node instances

        Raises:
            KeyError:
                If the address is a root address (containing only one address part)
                and a node exists in :attr:`root_nodes` that does **not** match
                the given ``cls``
        """
        if cls is None:
            cls = AddressNode

        if not isinstance(address, Address):
            address = Address(pattern=address)

        root_name = address.parts[0].part
        if root_name in self:
            address = address[1:]
            root = self[root_name]
            if root.__class__ is not cls:
                raise KeyError(f'Node with name "{root_name}" already exists')
            if not len(address):
                return root, root
            last_child = root.create_children_from_address(address)
        else:
            root, last_child = cls.create_from_address(address)
            self.add_root_instance(root)
        return root, last_child

    def find(self, address: StrOrAddress) -> Optional['AddressNode']:
        """Search for a node matching the given address

        Arguments:
            address: The address to search for
        """
        if not isinstance(address, Address):
            address = Address(pattern=address)

        root = self.get(address[0].pattern.lstrip('/'))
        if root is None:
            return None
        return root.find(address)

    def match(self, address: StrOrAddress) -> Iterator['AddressNode']:
        """Iterate through any nodes or child nodes matching the given address

        See :meth:`AddressNode.match`

        Arguments:
            address: The address to match
        """
        if not isinstance(address, Address):
            address = Address(pattern=address)

        for root in self:
            yield from root.match(address)

    def walk(self) -> Iterator['AddressNode']:
        """Iterate over all :attr:`root_nodes` and their children

        Calls :meth:`~AddressNode.walk` on each instances in :attr:`root_nodes`
        """
        for root in self:
            yield from root.walk()

    def __getitem__(self, key) -> 'AddressNode':
        return self.root_nodes[key]

    def get(self, key: str, default: Optional[Any] = None) -> Optional['AddressNode']:
        """Get the root node matching the given name.

        If not found, return the default value

        Arguments:
            key: The :attr:`~AddressNode.name`
            default: The value to return if not found
        """
        return self.root_nodes.get(key)

    def __contains__(self, key):
        return key in self.root_nodes

    def __len__(self):
        return len(self.root_nodes)

    def __iter__(self):
        yield from self.values()

    def keys(self) -> KeysView[str]:
        """Alias for :attr:`root_nodes.keys`
        """
        return self.root_nodes.keys()

    def values(self) -> ValuesView['AddressNode']:
        """Alias for :attr:`root_nodes.values`
        """
        return self.root_nodes.values()

    def items(self) -> ItemsView[str, 'AddressNode']:
        """Alias for :attr:`root_nodes.items`
        """
        return self.root_nodes.items()


class AddressNode:
    """A node within an OSC address space

    Attributes:
        children: Mapping of child nodes using the :attr:`name` as keys

    Arguments:
        name: The node :attr:`name`
        parent: The node :attr:`parent`
    """

    children: Dict[str, 'AddressNode']

    __slots__ = (
        '__name', '__parent', '__address', '__address_space', '__address_part',
        '__part_index', 'children', '__event_handler',
    )

    def __init__(self, name: str,
                       parent: Optional['AddressNode'] = None):

        self.__name = name
        self.__parent = parent
        self.__address = None
        self.__address_space = None
        self.__address_part = None
        self.__part_index = None
        self.__event_handler = None
        self.children = {}

    @property
    def name(self) -> str:
        """The node name
        """
        return self.__name

    @property
    def address(self) -> Address:
        """The full OSC address for the node
        """
        a = self.__address
        if a is not None:
            return a
        if self.is_root:
            a = self.__address = Address(pattern=f'/{self.name}')
        else:
            a = self.__address = self.parent.address / self.name
        return a

    @property
    def address_part(self) -> AddressPart:
        """The :class:`AddressPart` for the node within its :attr:`address`
        """
        p = self.__address_part
        if p is None:
            p = self.__address_part = self.address.parts[self.__part_index]
        return p

    @property
    def parent(self) -> Optional['AddressNode']:
        """The parent node, or ``None`` if this is the :attr:`root`
        """
        return self.__parent
    @parent.setter
    def parent(self, value: Optional['AddressNode']):
        if value is self.__parent:
            return
        if value is not None and self.name in value.children:
            raise KeyError(f'Node with name "{self.name}" already exists in "{value!r}"')
        if self.__parent is not None:
            del self.__parent.children[self.name]
        self.__parent = value
        if self.__parent is not None:
            self.__parent.children[self.name] = self
        self._reset_memoized_attrs()

    @property
    def part_index(self) -> int:
        """Index of the node :attr:`address_part`
        """
        ix = self.__part_index
        if ix is None:
            ix = self.__part_index = len(self.address) - 1
        return ix

    def _reset_memoized_attrs(self):
        self.__address = None
        self.__address_part = None
        self.__part_index = None
        if not self.is_root:
            self.__address_space = None
        for child in self:
            child._reset_memoized_attrs()

    @property
    def root(self) -> 'AddressNode':
        """The root node of the tree
        """
        if self.is_root:
            return self
        return self.parent.root

    @property
    def address_space(self) -> Optional[AddressSpace]:
        """The :class:`AddressSpace` the node belongs to
        """
        if self.is_root:
            return self.__address_space
        return self.root.address_space
    @address_space.setter
    def address_space(self, value: AddressSpace):
        if not self.is_root:
            raise ValueError('Only root nodes can belong to an AddressSpace')
        if value is self.__address_space:
            return
        if self.__address_space is not None:
            del self.__address_space.root_nodes[self.name]
        self.__address_space = value
        if self.__address_space is not None:
            if self.name not in self.__address_space:
                self.__address_space.add_root_instance(self)

    @property
    def is_root(self) -> bool:
        """``True`` if the node is at the root of the tree (has no :attr:`parent`)
        """
        return self.parent is None

    @property
    def event_handler(self) -> Optional[Event]:
        """An :class:`~pydispatch.dispatch.Event` instance used for callbacks
        """
        return self.__event_handler

    @property
    def has_callbacks(self) -> bool:
        """``True`` if any callbacks have been set on the node
        """
        h = self.event_handler
        if h is None:
            return False
        if len(h.listeners) or len(h.aio_listeners):
            return True
        return False

    def add_callback(self, cb: Callable, aio_loop: Optional['asyncio.BaseEventLoop'] = None):
        """Add a method, function or :term:`coroutine function` to the :attr:`event_handler`

        Arguments:
            cb: The callback function
            aio_loop: If the callback is a :term:`coroutine function`, the
                :class:`event loop <asyncio.BaseEventLoop>` associated with it

        The callback should accept the signature::

            def cb(node: oscpython.address.AddressNode,
                   message: oscpython.messages.Message,
                   timetag: oscpython.common.TimeTag) -> None:
                pass


        :Callback Arguments:

            node: :class:`AddressNode`
                The node instance that originated the event
            message: :class:`.messages.Message`
                The received message
            timetag: :class:`.common.TimeTag`
                Timestamp of when the message was received.
                See :meth:`.transport.BaseServer.handle_packet` for details

        """
        h = self.event_handler
        if h is None:
            h = self.__event_handler = Event(self.name)
        h.add_listener(cb, __aio_loop__=aio_loop)

    def remove_callback(self, cb: Callable):
        """Remove a callback previously attached by :meth:`add_callback`
        """
        self.event_handler.remove_listener(cb)
        if not self.has_callbacks:
            self.__event_handler = None

    def dispatch(self, message: 'oscpython.messages.Message', timetag: 'oscpython.common.TimeTag'):
        """Called when a message is received that matches this node :attr:`address`

        Triggers any callbacks registered in the :attr:`event_handler` and emits
        the ``'on_message'`` event on the :attr:`address_space`

        Arguments:
            message: The received message
            timetag: Timestamp of when the message was received.

        """
        h = self.event_handler
        if h is not None:
            h(self, message, timetag)
        sp = self.address_space
        if sp is not None:
            sp.emit('on_message', self.address, message, timetag)

    def find(self, address: StrOrAddress) -> Optional['AddressNode']:
        """Search for a node matching the given relative address

        Arguments:
            address: The address to search for
        """
        if not isinstance(address, Address):
            address = Address(pattern=address)
        ix = self.part_index
        try:
            part = address.parts[ix]
        except IndexError:
            return None
        if part.part != self.address_part.part:
            return None
        if len(address) == len(self.address):
            return self

        child_name = address.parts[ix+1].part
        child = self.get(child_name)
        if child is None:
            return None
        return child.find(address)

    def match(self, address: StrOrAddress) -> Iterator['AddressNode']:
        """Iterate through any nodes or child nodes matching the given address

        This uses the :meth:`Address.match` method to follow OSC
        pattern matching rules

        Arguments:
            address: The address to match

        Note:
            The address argument must be absolute
        """
        part_index = self.part_index
        my_part = self.address_part
        try:
            match_part = address.parts[part_index]
        except IndexError:
            return
        if match_part.match(my_part):
            if len(address) == len(self.address):
                yield self
            for child in self:
                yield from child.match(address)

    def walk(self) -> Iterator['AddressNode']:
        """Iterate through this node and all of its descendants
        """
        yield self
        for child in self:
            yield from child.walk()

    def create_message(self, *args, **kwargs) -> 'oscpython.messages.Message':
        """Create a :class:`~.messages.Message` using this node's :attr:`address`

        Positional and keyword arguments (``*args`` and ``**kwargs``)
        will be passed directly to :meth:`.messages.Message.create`
        """
        _import_message_classes()
        addr = self.address.copy()
        return Message.create(addr, *args, **kwargs)

    def create_bundled_message(self, *args, **kwargs) -> 'oscpython.messages.Bundle':
        """Create a :class:`~.messages.Bundle` containing a :class:`~.messages.Message`
        using this node's :attr:`address`

        Keyword arguments (``**kwargs``) will be passed to the
        Bundle's ``__init__`` method and positional arguments (``*args``)
        will be passed to :meth:`.messages.Message.create`
        """
        msg = self.create_message(*args)
        bun = Bundle(**kwargs)
        bun.add_packet(msg)
        return bun

    def add_child(self, name: str, cls: Optional[type] = None) -> 'AddressNode':
        """Add a child node to this point in the tree

        Arguments:
            name (str): The node :attr:`name`
            cls (optional): A subclass of :class:`AddressNode` to use when
                creating the child node. If not provided, the class is inherited
        """
        if cls is None:
            cls = self.__class__
        if name in self:
            obj = self[name]
            if cls is not obj.__class__:
                raise KeyError(f'Node with name "{name}" already exists')
            return obj
        obj = cls(name, self)
        self.children[name] = obj
        return obj

    def add_child_instance(self, child: 'AddressNode'):
        """Add an existing :class:`AddressNode` instance to :attr:`children`

        Arguments:
            child: The instance to add
        """
        if child.name in self:
            _child = self[child.name]
            if _child is not child:
                raise KeyError(f'Node with name "{child.name}" already exists')
        child.parent = self
        self.children[child.name] = child
        return child

    def create_children_from_address(self, address: StrOrAddress) -> 'AddressNode':
        """Create node or nodes from the given (relative) OSC address and
        return the final node of the tree

        Arguments:
            address: The OSC address (relative to this node)
        """
        if not isinstance(address, Address):
            address = Address(pattern=address)
        child_name = address.parts[0].part
        address = address[1:]
        child = self.get(child_name)
        if child is None:
            child = self.add_child(child_name)
        if not len(address):
            return child
        return child.create_children_from_address(address)

    @classmethod
    def create_from_address(cls, address: StrOrAddress) -> Tuple['AddressNode', 'AddressNode']:
        """Create node or nodes from the given OSC address

        Arguments:
            address: The OSC address

        Returns
        -------
        node : AddressNode
            The first (root) node created
        last_child : AddressNode
            The last child created (the end of the address string)
        """
        if not isinstance(address, Address):
            address = Address(pattern=address)
        name = address.parts[0].part
        address = address[1:]
        node = cls(name)
        if not len(address):
            return node, node
        last_child = node.create_children_from_address(address)
        return node, last_child

    def __getitem__(self, key):
        return self.children[key]

    def get(self, key, default=None) -> Optional['AddressNode']:
        """Get the child node matching the given name.

        If not found, return the default value
        """
        return self.children.get(key)

    def __contains__(self, key):
        return key in self.children

    def __len__(self):
        return len(self.children)

    def __iter__(self):
        yield from self.values()

    def keys(self) -> KeysView[str]:
        """Alias for :meth:`children.keys`
        """
        return self.children.keys()

    def values(self) -> ValuesView['AddressNode']:
        """Alias for :meth:`children.values`
        """
        return self.children.values()

    def items(self) -> ItemsView[str, 'AddressNode']:
        """Alias for :meth:`children.items`
        """
        return self.children.items()

    def __repr__(self):
        return f'<{self.__class__}: "{self.address.pattern}">'

    def __str__(self):
        return f'{self.name}'
