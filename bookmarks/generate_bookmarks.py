from __future__ import annotations
import typing
import urllib.parse
import json
import dataclasses
import pprint
import datetime
import base64
import lz4.block
import requests


@dataclasses.dataclass
class Bookmark:
    title: str
    uri: str
    parent: str
    modified: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    created: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    icon_uri: str = '/favicon.ico'

    def __post_init__(self):
        if not self.icon_uri:
            self.icon_uri = '/favicon.ico'
        res = urllib.parse.urlparse(self.icon_uri)
        if not res.netloc:
            if res.path.startswith('/'):
                base_res = urllib.parse.urlparse(self.uri)
                self.icon_uri = urllib.parse.urlunparse((base_res.scheme, base_res.netloc, res.path, res.params, res.query, res.fragment))
            else:
                self.icon_uri = urllib.parse.urljoin(self.uri, self.icon_uri)

    @property
    def path(self):
        return f'{self.parent}.{self.title}'


@dataclasses.dataclass
class Folder:
    title: str
    parent: str
    modified: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    created: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    children: typing.List[typing.Union[Folder, Bookmark]] = dataclasses.field(default_factory=list)

    def add(self, child: typing.Union[Folder, Bookmark]):
        self.children.append(child)

    @property
    def path(self):
        if self.parent:
            return f'{self.parent}.{self.title}'
        else:
            return self.title


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
            folder = Folder(d['title'], c.path if c is not None else '', _t(d['lastModified']), _t(d['dateAdded']))
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
                c.path,
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


def icon_uri2data(icon_uri):
    if icon_uri.startswith('data:image/'):
        return icon_uri
    try:
        resp = requests.get(icon_uri, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f'[warn] catch exception: {e}')
        return ''
    if resp.status_code != 200:
        return ''
    img_type = resp.headers.get('Content-Type')
    data = base64.b64encode(resp.content).decode()
    return f'data:{img_type};base64,{data}'


def render_as_html(folder: Folder, path='') -> str:

    def _rec(x: typing.Union[Folder, Bookmark]) -> str:
        if isinstance(x, Folder):
            return _df(x)
        else:
            return _db(x)

    def _df(f: Folder) -> str:
        children_html = list(filter(None, [_rec(child) for child in f.children]))
        if not path or (path and f.path.startswith(path)) or len(children_html) > 0:
            if len(children_html) == 1:
                return children_html[0]
            return f'<p>{f.title}:</p><ol><li>{"</li><li>".join(children_html)}</li></ol>'
        return ''

    def _db(b: Bookmark) -> str:
        print(b.icon_uri)
        if path and not b.path.startswith(path):
            return ''
        icon = icon_uri2data(b.icon_uri)
        print(b.uri, icon)
        icon_html = '' if not icon else f'<img src="{icon}" width="32" height="32" />'
        return f'<a href="{b.uri}" referrerpolicy="no-referrer" target="_blank">{icon_html}{b.title}</a>'

    return f"""
<html lang="zh-CN">
    <head>
        <meta charset="UTF-8" />
        <title>Bookmarks</title>
    </head>
    <body>
        {_rec(folder)}
    </body>
</html>"""


if __name__ == "__main__":
    with open('bookmarks.html', 'w+') as f:
        f.write(render_as_html(load_firefox('bookmarks.jsonlz4'), 'toolbar.Blog'))