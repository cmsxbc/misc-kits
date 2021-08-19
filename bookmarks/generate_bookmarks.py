from __future__ import annotations
import sys
import os.path
import argparse
import typing
import urllib.parse
import json
import dataclasses
import datetime
import base64
import hashlib
import lz4.block
import aiohttp
import asyncio


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
                self.icon_uri = urllib.parse.urlunparse((
                    base_res.scheme, base_res.netloc, res.path, res.params, res.query, res.fragment))
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
        return datetime.datetime.fromtimestamp(timestamp / 1e6)

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


async def bookmark_icon_uri2data(session: aiohttp.ClientSession, b: Bookmark):
    if b.icon_uri.startswith('data:image/'):
        return
    print(f'[trace] aio get: {b.icon_uri}')
    try:
        async with session.get(b.icon_uri) as resp:
            data = await resp.read()
            if resp.status != 200:
                return
            img_type = resp.headers.get('Content-Type')
            data = base64.b64encode(data).decode()
            print(f'[trace] aio get done: {b.icon_uri}')
            b.icon_uri = f'data:{img_type};base64,{data}'
    except (aiohttp.ClientOSError, aiohttp.ServerTimeoutError, asyncio.exceptions.TimeoutError) as e:
        print(f'[warn] while fetch {b.icon_uri} catch exception: {e}')
        return


def get_svg_uri(b: Bookmark):
    xml_lines = [
        ('<?xml version="1.0" standalone="no"?>'
         '<svg width="32" height="32" xmlns="http://www.w3.org/2000/svg" version="1.1">')
    ]
    values = hashlib.md5(b.icon_uri.encode()).digest() * 2
    for x in range(4):
        for y in range(4):
            color = values[x*4+y:][:3].hex()
            xml_lines.append(f'<rect width="8" height="8" x="{8*x}" y="{8*y}" fill="#{color}"></rect>')
    xml_lines.append('</svg>')
    data = base64.b64encode(''.join(xml_lines).encode()).decode()
    return f'data:image/svg+xml;base64,{data}'


def render_as_html(folder: Folder, path='', include_icon=True) -> str:
    def _rec_icon(s: aiohttp.ClientSession, t: typing.List, x: typing.Union[Folder, Bookmark]):
        if isinstance(x, Folder):
            for child in x.children:
                _rec_icon(s, t, child)
            return
        elif path and not x.path.startswith(path):
            return
        t.append(asyncio.ensure_future(bookmark_icon_uri2data(s, x)))

    async def get_all_icons():
        timeout = aiohttp.ClientTimeout(60, 10, 25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = []
            _rec_icon(session, tasks, folder)
            await asyncio.gather(*tasks)

    def _rec(x: typing.Union[Folder, Bookmark], d=0) -> str:
        if isinstance(x, Folder):
            return _df(x, d)
        else:
            return _db(x)

    def _df(f: Folder, d=0) -> str:
        children_html_list = list(filter(None, [_rec(child, d + 1) for child in f.children]))
        if not path or (path and f.path.startswith(path)) or len(children_html_list) > 0:
            if len(children_html_list) == 1:
                return children_html_list[0]
            indent1 = ' ' * 4 * d * 2
            indent2 = ' ' * 4 * (d * 2 + 1)
            children_html = f"</li>\n{indent2}<li>".join(children_html_list)
            return f'<p>{f.title}:</p>\n{indent1}<ol><li>{children_html}</li>\n{indent1}</ol>'
        return ''

    def _db(b: Bookmark) -> str:
        if path and not b.path.startswith(path):
            return ''
        if include_icon:
            icon = b.icon_uri if b.icon_uri.startswith('data:image/') else get_svg_uri(b)
        else:
            icon = ''
        # print(b.uri, b.icon_uri)
        icon_html = '' if not icon else f'<img src="{icon}" width="32" height="32" />'
        return f'<div class="bookmark"><a href="{b.uri}" referrerpolicy="no-referrer" target="_blank">{icon_html}<p>{b.title}</p></a></div>'

    if include_icon:
        asyncio.run(get_all_icons())

    return f"""
<html lang="zh-CN">
    <head>
        <meta charset="UTF-8" />
        <title>Bookmarks</title>
        <style>
        ol {{
            counter-reset: section;
            list-style-type: none;
        }}
        .bookmark::before {{
            counter-increment: section;
            content: counters(section, ".", decimal-leading-zero) ". ";
            padding-right: .5rem;
            display:inline-block;
        }}
        .bookmark img,p {{
            display: inline-block;
            vertical-align: middle;
        }}
        .bookmark p {{
            text-indent: .6rem;
        }}
        </style>
    </head>
    <body>
        {_rec(folder)}
    </body>
</html>"""


def get_latest_firefox() -> typing.Optional[str]:
    firefox_dir = os.path.expanduser('~/.mozilla/firefox/')
    if not os.path.exists(firefox_dir):
        print('[error] it seems that no firefox data exist!', file=sys.stderr)
        return ''
    timestamp = 0
    candidate = ''
    for sub_path in os.listdir(firefox_dir):
        if not sub_path.endswith('.default-release'):
            continue
        bookmark_dir_path = os.path.join(firefox_dir, sub_path, 'bookmarkbackups')
        if not os.path.exists(bookmark_dir_path):
            continue
        for backup_path in os.listdir(bookmark_dir_path):
            backup_path = os.path.join(bookmark_dir_path, backup_path)
            f_stat = os.stat(backup_path)
            if f_stat.st_mtime > timestamp:
                timestamp = f_stat.st_mtime
                candidate = backup_path

    return candidate


def main():
    parser = argparse.ArgumentParser(description="render firefox bookmarks as html", add_help=True)
    parser.add_argument('-i', dest='input_path', required=False, default=None)
    parser.add_argument('output_path')
    parser.add_argument('-p', '--path-filter', dest='path_filter', default='')
    parser.add_argument('--skip-empty', dest='skip_empty', action='store_true')
    parser.add_argument('--no-icon', dest='include_icon', action='store_false')

    args = parser.parse_args()

    if args.input_path is None:
        args.input_path = get_latest_firefox()
        print(f'[warn]use backup: {args.input_path}')

    if not os.path.exists(args.input_path):
        print(f'[error]{args.input_path} does not exist!', file=sys.stderr)
        sys.exit(1)

    if os.path.exists(args.output_path):
        print(f'[warn]{args.output_path} exists!', file=sys.stderr)
        ans = input(f'Do you want to overwrite "{args.output_path}"?[Yy/Nn]')
        if ans.lower() != 'y':
            sys.exit(1)

    with open(args.output_path, 'w+') as of:
        folder = load_firefox(args.input_path, args.skip_empty)
        of.write(render_as_html(folder, args.path_filter, args.include_icon))


if __name__ == "__main__":
    main()
