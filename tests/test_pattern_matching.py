import pytest

from oscpython.messages import Address, AddressPart


def mutate_pattern_part(part, should_match=True):
    if should_match:
        yield '*'
        yield '{%s,NONE}' % (part)
    else:
        yield '{NONE,NOTHING}'
    for i in range(len(part)):
        if part[i] != 'z':
            c = chr(ord(part[i])+1)
            if should_match:
                bracket_strings = [f'[{part[i]}-z]', f'[!{c}-z]']
            else:
                bracket_strings = [f'[!{part[i]}-z]', f'[{c}-z]']
        else:
            if should_match:
                bracket_strings = ['[y-z]', '[!a-y]']
            else:
                bracket_strings = ['[!y-z]', '[a-y]']
        for bracket_string in bracket_strings:
            yield ''.join([part[:i], bracket_string, part[i+1:]])
        if should_match:
            newpart = list(part)
            newpart[i] = '?'
            yield ''.join(newpart)
        else:
            if 0 < i < len(part)-1:
                yield ''.join([part[:i], '?', part[i+2:]])


def mutate_patterns(pattern, should_match=True, use_double_slash=False):
    pattern = pattern.lstrip('//').split('/')
    if should_match:
        yield '/{}'.format('/'.join(pattern))
    else:
        _p = pattern[:]
        _p[-1] = _p[-1].upper()
        yield '/{}'.format('/'.join(_p))
    for i, part in enumerate(pattern):
        if use_double_slash:
            p = pattern.copy()
            p[i] = f'/{p[i]}'
            yield '/{}'.format('/'.join(p))
        for _part in mutate_pattern_part(part, should_match):
            p = pattern.copy()
            p[i] = _part
            yield '/{}'.format('/'.join(p))
            if use_double_slash and i > 0:
                p[i-1] = f'/{p[i-1]}'
                yield '/{}'.format('/'.join(p))

@pytest.fixture
def patterns():
    base_pattern = '/foo/bar/baz/blah/stuff/and/lotsofthings'
    d = dict(
        base_pattern=base_pattern,
        matched=tuple(mutate_patterns(base_pattern, should_match=True)),
        unmatched=tuple(mutate_patterns(base_pattern, should_match=False)),
        double_slash=tuple(mutate_patterns(base_pattern, should_match=True, use_double_slash=True)),
    )
    return d

def test_address_manipulation():
    address = Address(pattern='/foo/bar')
    assert len(address) == 2
    address = address / 'baz'
    assert len(address) == 3
    assert address.pattern == '/foo/bar/baz'

    assert address[0].pattern == '/foo'
    assert address[1].pattern == 'bar'
    assert address[2].pattern == 'baz'

    foobarbaz = address[:]
    assert foobarbaz.pattern == address.pattern
    foobar = address[:2]
    assert foobar.pattern == '/foo/bar'
    barbaz = address[1:3]
    assert barbaz.pattern == 'bar/baz'

    for part1, part2, s in zip(address, foobarbaz, ['foo', 'bar', 'baz']):
        assert part1.part == part2.part == s
        assert part1 == part2
        assert part1 != AddressPart(part='a', is_root=False)
        assert part2 != AddressPart(part='a', is_root=True)
        assert part1 != AddressPart(part=s, is_root=not part1.is_root)
        assert part2 != AddressPart(part=s, is_root=not part1.is_root)


def test_wildcards(patterns):
    concrete_pattern = Address(pattern=patterns['base_pattern'])
    assert concrete_pattern.pattern_parts == tuple(patterns['base_pattern'].split('/')[1:])
    assert concrete_pattern.is_concrete

    for pattern in patterns['matched']:
        # print(f'{concrete_pattern.pattern} == {pattern}')
        a = Address(pattern=pattern)
        if pattern.lower() == patterns['base_pattern']:
            assert a.is_concrete
        else:
            assert not a.is_concrete
        assert concrete_pattern.match(pattern) is True
        assert concrete_pattern.match(a) is True
        assert a.match(concrete_pattern) is True

        truncated_pattern = '/'.join(pattern.split('/')[:-1])
        a = Address(pattern=truncated_pattern)
        assert concrete_pattern.match(truncated_pattern) is False
        assert concrete_pattern.match(a) is False
        assert a.match(concrete_pattern) is False

        extra_pattern = f'{pattern}/extrapart'
        a = Address(pattern=extra_pattern)
        assert concrete_pattern.match(extra_pattern) is False
        assert concrete_pattern.match(a) is False
        assert a.match(concrete_pattern) is False

    for pattern in patterns['unmatched']:
        # print(f'{concrete_pattern.pattern} != {pattern}')
        a = Address(pattern=pattern)
        if pattern.lower() == patterns['base_pattern']:
            assert a.is_concrete
        else:
            assert not a.is_concrete
        assert concrete_pattern.match(pattern) is False
        assert concrete_pattern.match(a) is False
        assert a.match(concrete_pattern) is False

        truncated_pattern = '/'.join(pattern.split('/')[:-1])
        a = Address(pattern=truncated_pattern)
        assert concrete_pattern.match(truncated_pattern) is False
        assert concrete_pattern.match(a) is False
        assert a.match(concrete_pattern) is False

        extra_pattern = f'{pattern}/extrapart'
        a = Address(pattern=extra_pattern)
        assert concrete_pattern.match(extra_pattern) is False
        assert concrete_pattern.match(a) is False
        assert a.match(concrete_pattern) is False

    for pattern in patterns['double_slash']:
        # print(f'{concrete_pattern.pattern} == {pattern}')
        a = Address(pattern=pattern)
        if '//' in pattern:
            assert a.parts[0].part.startswith('/')
        if pattern.lower() == patterns['base_pattern']:
            assert a.is_concrete
        else:
            assert not a.is_concrete
        assert concrete_pattern.match(pattern) is True
        assert concrete_pattern.match(a) is True
        assert a.match(concrete_pattern) is True
