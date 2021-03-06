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
import logging
import lz4.block
import aiohttp
import asyncio


logging.basicConfig()
logger = logging.getLogger('bookmarks')


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


def t(timestamp):
    return datetime.datetime.fromtimestamp(timestamp / 1e6)


def general_builder(root: typing.Dict, folder_type, bookmark_type, name_key: str, uri_key: str,
                    created_key='', modified_key='', icon_key='',
                    type_key='type', children_key='children',
                    skip_empty=False, skip_func: typing.Callable[[typing.Dict], bool] = lambda d: True):
    def _rec(d: typing.Union[list, dict], c: typing.Optional[Folder] = None) -> Folder:
        if isinstance(d, list):
            assert isinstance(c, Folder)
            for child in d:
                _rec(child, c)
            return c
        assert isinstance(d, dict), f"Unsupported type {type(d)} of {d}"
        if skip_func(d):
            logger.warning('skip %s', d)
            return c
        optional_fields = {}
        if modified_key:
            optional_fields['modified'] = t(d[modified_key])
        if created_key:
            optional_fields['created'] = t(d[created_key])
        if d[type_key] == folder_type:
            if skip_empty and len(d.get(children_key, [])) <= 0:
                logger.warning('skip empty: %s', d)
                return c
            folder = Folder(d[name_key], c.path if c is not None else '', **optional_fields)
            _rec(d[children_key], folder)
            if skip_empty and len(folder.children) <= 0:
                return c
            if c is not None:
                c.add(folder)
                return c
            else:
                return folder
        elif d[type_key] == bookmark_type:
            if icon_key:
                optional_fields['icon_uri'] = d.get(icon_key)
            c.add(Bookmark(d[name_key], d[uri_key], c.path, **optional_fields))
            return c
        assert False, f"Unknown bookmark type: {d['type']}"

    return _rec(root)


def load_firefox(filepath, skip_empty=False):
    with open(filepath, 'rb') as f:
        assert f.read(8) == b'mozLz40\x00'
        data = json.loads(lz4.block.decompress(f.read()))
    return general_builder(
        data,
        folder_type='text/x-moz-place-container',
        bookmark_type='text/x-moz-place',
        name_key='title',
        uri_key='uri',
        created_key='dateAdded',
        modified_key='lastModified',
        icon_key='iconuri',
        skip_empty=skip_empty,
        skip_func=lambda x: x.get('iconuri', '').startswith('fake-favicon-uri:')
    )


def load_chrome(filepath, skip_empty=False):
    with open(filepath, 'r') as f:
        data = json.load(f)
    return general_builder(
        {'children': list(data['roots'].values()), 'name': 'root', 'type': 'folder'},
        folder_type='folder',
        bookmark_type='url',
        name_key='name',
        uri_key='url',
        skip_empty=skip_empty,
        skip_func=lambda x: x.get('url', '').startswith('chrome://')
    )


async def bookmark_icon_uri2data(session: aiohttp.ClientSession, b: Bookmark):
    if b.icon_uri.startswith('data:image/'):
        return
    logger.debug('aio get: %s', b.icon_uri)
    try:
        async with session.get(b.icon_uri) as resp:
            data = await resp.read()
            if resp.status != 200:
                return
            img_type = resp.headers.get('Content-Type')
            data = base64.b64encode(data).decode()
            if not data:
                logger.warning('aio get finished: %s, but there is no data', b.icon_uri)
                return ''
            logger.debug('aio get done: %s', b.icon_uri)
            b.icon_uri = f'data:{img_type};base64,{data}'
    except (aiohttp.ClientOSError, aiohttp.ServerTimeoutError, asyncio.exceptions.TimeoutError) as e:
        logger.warning('while fetch %s catch exception: %s', b.icon_uri, e)
        return
    except Exception as e:
        logger.error('while fetch %s catch exception: %s', b.icon_uri, e)
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

    def _attr_url(value):
        mapping = {
            '"': '%22',
            '>': '%3E'
        }
        for o, r in mapping.items():
            value = value.replace(o, r)
        res = urllib.parse.urlparse(value)
        validate_schemes = {
            'https',
            'http',
            'ftp',
        }
        if res.scheme in validate_schemes:
            return value
        return f'https://invalid-schema/{value}'

    def _element(value):
        mapping = {
            '<': '&lt;',
            '>': '&gt;',
            '&': '&amp;',
            '"': '&quot;',
            "'": '&#x27;'
        }
        for o, r in mapping.items():
            value = value.replace(o, r)
        return value

    def _df(f: Folder, d=0) -> str:
        children_html_list = list(filter(None, [_rec(child, d + 1) for child in f.children]))
        if not path or (path and f.path.startswith(path)) or len(children_html_list) > 0:
            if len(children_html_list) == 1:
                return children_html_list[0]
            indent1 = ' ' * 4 * d * 2
            indent2 = ' ' * 4 * (d * 2 + 1)
            children_html = f"</li>\n{indent2}<li>".join(children_html_list)
            return f'<p>{_element(f.title)}:</p>\n{indent1}<ol><li>{children_html}</li>\n{indent1}</ol>'
        return ''

    def _db(b: Bookmark) -> str:
        if path and not b.path.startswith(path):
            return ''
        if include_icon:
            icon = b.icon_uri if b.icon_uri.startswith('data:image/') else get_svg_uri(b)
        else:
            icon = ''
        icon_html = '' if not icon else f'<img src="{icon}" width="32" height="32" />'
        return (
            '<div class="bookmark">'
            f'<a href="{_attr_url(b.uri)}" referrerpolicy="no-referrer" target="_blank">'
            f'{icon_html}<p>{_element(b.title)}</p>'
            '</a></div>'
        )

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
        logger.error('it seems that no firefox data exist!')
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


def get_chromium(name='chromium'):
    bookmark_path = os.path.expanduser(f'~/.config/{name}/Default/Bookmarks')
    if not os.path.exists(bookmark_path):
        logger.error('it seems that no %s(based on chromium) data exist!', name)
        return ''
    return bookmark_path


def get_chrome():
    return get_chromium('google-chrome')


def main():
    browser_mapping = {
        'firefox': {
            'loader': load_firefox,
            'get_default': get_latest_firefox
        },
        'chrome': {
            'loader': load_chrome,
            'get_default': get_chrome
        },
        'chromium': {
            'loader': load_chrome,
            'get_default': get_chromium
        }
    }
    parser = argparse.ArgumentParser(description="render browser bookmarks as html", add_help=True)
    parser.add_argument('-b', '--browser', dest='browser', required=True, choices=list(browser_mapping.keys()))
    parser.add_argument('output_path', help='/path/for/the/generated/html/to/be/stored')
    parser.add_argument('-i', dest='input_path', required=False, default=None,
                        help='/path/to/bookmarks/file, if not supplied, the default (across the browser) will be used.')
    parser.add_argument('-p', '--path-filter', dest='path_filter', default='',
                        help='filter bookmarks by path, use "." to split parent and child')
    parser.add_argument('--skip-empty', dest='skip_empty', action='store_true',
                        help='skip empty folder')
    parser.add_argument('--no-icon', dest='include_icon', action='store_false',
                        help='do not include icons in generated html')
    parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')
    parser.add_argument('-v', '--verbose', action='count', default=0)

    args = parser.parse_args()

    logger.setLevel(logging.ERROR - 10 * args.verbose)

    if args.input_path is None:
        args.input_path = browser_mapping[args.browser]['get_default']()
        logger.info('use default of %s: %s', args.browser, args.input_path)

    if not os.path.exists(args.input_path):
        logger.error('%s does not exist!', args.input_path)
        sys.exit(1)

    if os.path.exists(args.output_path):
        logger.warning('%s exists!', args.output_path)
        if not args.yes and input(f'Do you want to overwrite "{args.output_path}"?[Yy/Nn]').lower() != 'y':
            sys.exit(1)

    with open(args.output_path, 'w+') as of:
        folder = browser_mapping[args.browser]['loader'](args.input_path, args.skip_empty)
        of.write(render_as_html(folder, args.path_filter, args.include_icon))


if __name__ == "__main__":
    main()
