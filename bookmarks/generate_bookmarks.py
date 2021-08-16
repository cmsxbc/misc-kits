from __future__ import annotations
import typing
import urllib.parse
import json
import dataclasses
import pprint
import datetime
import lz4.block


@dataclasses.dataclass
class Bookmark:
    title: str
    uri: str
    modified: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    created: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    icon_uri: str = 'favicon.ico'

    def __post_init__(self):
        urllib.parse.urlparse(self.icon_uri)


@dataclasses.dataclass
class Folder:
    title: str
    modified: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    created: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    children: typing.List[typing.Union[Folder, Bookmark]] = dataclasses.field(default_factory=list)

    def add(self, child: typing.Union[Folder, Bookmark]):
        self.children.append(child)


def load_firefox(filepath, skip_empty=True):

    def _t(timestamp):
        return datetime.datetime.fromtimestamp(timestamp/1e6)

    def _rec(d: typing.Union[list, dict], c: typing.Optional[Folder] = None) -> Folder:
        if isinstance(d, list):
            assert isinstance(c, Folder)
            for child in d:
                _rec(child, c)
            return c
        assert isinstance(d, dict), f"Unsupported type {type(d)} of {d}"
        if d['type'] == 'text/x-moz-place-container':
            if skip_empty and len(d.get('children', [])) <= 0:
                return c
            folder = Folder(d['title'], _t(d['lastModified']), _t(d['dateAdded']))
            _rec(d['children'], folder)
            if skip_empty and len(folder.children) <= 0:
                return c
            if c is not None:
                c.add(folder)
                return c
            else:
                return folder
        elif d['type'] == 'text/x-moz-place':
            if d.get('iconuri', '').startswith('fake-favicon-uri:'):
                # assume this is all firefox special.
                print(f"[warn] skip {d}")
                return c
            c.add(Bookmark(
                d['title'],
                d['uri'],
                _t(d['lastModified']),
                _t(d['dateAdded']),
                d.get('iconuri', '')
            ))
            return c
        assert False, f"Unknown bookmark type: {d['type']}"

    with open(filepath, 'rb') as f:
        assert f.read(8) == b'mozLz40\x00'
        data = json.loads(lz4.block.decompress(f.read()))
        ret = _rec(data)

    return ret


if __name__ == "__main__":
    folder = load_firefox('bookmarks.jsonlz4')
    pprint.pprint(dataclasses.asdict(folder))