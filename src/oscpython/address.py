from typing import (
    Optional, Sequence, List, Dict, Tuple, Union, Iterator, Any,
    KeysView, ValuesView, ItemsView,
)

from oscpython.messages import Address, AddressPart

StrOrAddress = Union[str, Address]


class AddressSpace:
    """An OSC address space, container for root (top-level)
    :class:`AddressNode` instances

    Attributes:
        root_nodes: Mapping of root nodes using the :attr:`~AddressNode.name`
            as keys
    """

    root_nodes: Dict[str, 'AddressNode']

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
        '__part_index', 'children',
    )

    def __init__(self, name: str,
                       parent: Optional['AddressNode'] = None):

        self.__name = name
        self.__parent = parent
        self.__address = None
        self.__address_space = None
        self.__address_part = None
        self.__part_index = None
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
        """The :class:`~.messages.AddressPart` for the node within its :attr:`address`
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

        This uses the :meth:`~.messages.Address.match` method to follow OSC
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
