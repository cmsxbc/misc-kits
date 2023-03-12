from __future__ import annotations

import functools
import sqlite3
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
import collections
import re
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
    tags: typing.Set[str] = dataclasses.field(default_factory=set)
    icon_data_uri: str = ''
    icon_updated: bool = dataclasses.field(init=False, default=False)

    def __post_init__(self):
        self.validate()
        if not self.icon_uri:
            self.icon_uri = '/favicon.ico'
        self.update_icon_uri()

    @property
    def path(self):
        return f'{self.parent}.{self.title}'

    def validate(self):
        uri_obj = urllib.parse.urlparse(self.uri)
        if not uri_obj.netloc:
            raise ValueError("lack of netloc")
        if not uri_obj.scheme:
            raise ValueError("lack of scheme")
        if uri_obj.scheme not in ("https", "http"):
            raise ValueError(f"Invalid {uri_obj.scheme=}")

    def update_icon_uri(self):
        res = urllib.parse.urlparse(self.icon_uri)
        if not res.netloc:
            if res.path.startswith('/'):
                base_res = urllib.parse.urlparse(self.uri)
                self.icon_uri = urllib.parse.urlunparse((
                    base_res.scheme, base_res.netloc, res.path, res.params, res.query, res.fragment))
            else:
                self.icon_uri = urllib.parse.urljoin(self.uri, self.icon_uri)

    def to_sqlite_tuple(self):
        return self.title, self.uri, self.icon_uri, self.icon_data_uri, ";".join(self.tags)


@dataclasses.dataclass
class Folder:
    title: str
    parent: str
    modified: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    created: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now)
    children: list[Folder | Bookmark] = dataclasses.field(default_factory=list)

    def add(self, child: Folder | Bookmark):
        self.children.append(child)

    @property
    def path(self):
        if self.parent:
            return f'{self.parent}.{self.title}'
        else:
            return self.title


def t(timestamp):
    return datetime.datetime.fromtimestamp(timestamp / 1e6)


def general_builder(root: dict, folder_type, bookmark_type, name_key: str, uri_key: str,
                    created_key='', modified_key='', icon_key='',
                    type_key='type', children_key='children',
                    skip_empty=False, skip_func: typing.Callable[[dict], bool] = lambda _: True):
    def _rec(d: list | dict, c: typing.Optional[Folder] = None) -> Folder:
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
            _rec(d.get(children_key, []), folder)
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


async def bookmark_icon_uri2data(session: aiohttp.ClientSession, b: Bookmark, icon_cache_dir: typing.Optional[str], force=False):
    b.icon_updated = False
    if b.icon_uri.startswith('data:image/'):
        return

    async def _get():
        cache_path = ''
        if icon_cache_dir:
            cache_path = os.path.join(icon_cache_dir, base64.b32encode(b.icon_uri.encode()).decode())
            if not force and os.path.exists(cache_path):
                logger.debug('use cache for %s: %s', b.icon_uri, cache_path)
                with open(cache_path) as f:
                    b.icon_data_uri = f.read()
                return
        logger.debug('aio get: %s', b.icon_uri)
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
            new_icon_data_uri = f'data:{img_type};base64,{data}'
            b.icon_updated = b.icon_data_uri != new_icon_data_uri
            b.icon_data_uri = new_icon_data_uri
            if cache_path:
                with open(cache_path, 'w+') as f:
                    f.write(b.icon_data_uri)
        return True

    async def _get_icon_url():
        logger.warning('try get icons from page for %s', b.title)
        async with session.get(b.uri) as resp:
            data = await resp.read()
            if resp.status != 200:
                logger.warning('cannot fetch data from %s, got http code: %d', b.uri, resp.status)
                return
            html = data.decode(resp.charset if resp.charset else "utf-8")
            if ml := re.search(r'<link\s+[^>]*rel=(?P<quote>[\'"]?)[^\'">]*icon[^\'"]*(?P=quote)[^>]*>', html):
                logger.debug('link matched: %s', ml.group(0))
                if m := re.search(r'href=(?P<quote>[\'"]?)(?P<url>[^\'"]*?)(?P=quote)(\s|>)', ml.group(0)):
                    logger.debug('href matched: %s', m.group(0))
                    old_uri = b.icon_uri
                    b.icon_uri = m.group('url')
                    b.update_icon_uri()
                    return b.icon_uri != old_uri
                else:
                    logger.warning('cannot get icon url from icon link tag from %s', b.uri)
            else:
                logger.warning('cannot get icon link tag from %s', b.uri)

    async def _retry(func, err_msg, retry_count):
        while retry_count > 0:
            try:
                return True, await func()
            except (aiohttp.ClientOSError, aiohttp.ServerTimeoutError, asyncio.exceptions.TimeoutError) as e:
                retry_count -= 1
                logger.warning('while %s catch exception: %s, remain retry: %d', err_msg, e, retry_count)
        return False, None

    try:
        if all(await _retry(_get, b.icon_uri, 3)):
            return
        if not all(await _retry(_get_icon_url, b.uri, 3)):
            logger.warning('failed to retrieve icon from page for %s(%s)', b.title, b.uri)
            return
        await _retry(_get, b.icon_uri, 3)
    except Exception as e:
        logger.error('while fetch %s catch exception: %s', b.icon_uri, e)
        return


async def get_bookmark_title(session: aiohttp.ClientSession, bookmark: Bookmark):
    if bookmark.title:
        return
    logger.warning('try get title from page for %s', bookmark.uri)

    async def _get():
        async with session.get(bookmark.uri) as resp:
            data = await resp.read()
            if resp.status != 200:
                logger.warning('cannot fetch data from %s, got http code: %d', bookmark.uri, resp.status)
                return
            html = data.decode(resp.charset if resp.charset else "utf-8")
            if ml := re.search(r'<title>([^<]*)</title>', html, re.IGNORECASE|re.MULTILINE):
                logger.debug('%s title matched: %s', bookmark.uri, ml.group(0))
                bookmark.title = ml.group(1)
            else:
                logger.warning('cannot get title from %s', bookmark.uri)
    try:
        await _get()
    except (aiohttp.ClientOSError, aiohttp.ServerTimeoutError, asyncio.exceptions.TimeoutError) as e:
        logger.warning('while fetch %s catch exception: %s', bookmark.uri, e)


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


def get_all_info(folder, paths: list[str] = None, icon_cache_dir=None, get_title=False, force=False):

    _funcs = [
        functools.partial(bookmark_icon_uri2data, icon_cache_dir=icon_cache_dir, force=force)
    ]
    if get_title:
        _funcs.append(get_bookmark_title)

    def _rec(s: aiohttp.ClientSession, t: list, x: Folder | Bookmark | list[Bookmark], funcs: list[typing.Callable[[aiohttp.ClientSession, Bookmark], typing.Coroutine]]):
        if isinstance(x, list):
            for b in x:
                _rec(s, t, b, funcs)
        elif isinstance(x, Folder):
            for child in x.children:
                _rec(s, t, child, funcs)
        elif paths and not any(x.path.startswith(path) for path in paths):
            pass
        else:
            t.extend(asyncio.ensure_future(func(s, x)) for func in funcs)

    async def _do():
        timeout = aiohttp.ClientTimeout(60, 10, 25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = []
            _rec(session, tasks, folder, _funcs)
            await asyncio.gather(*tasks)

    asyncio.run(_do())


def escape_attr_url(value):
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


def escape_element(value):
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


def convert2list_with_tags(folder: Folder, paths: list[str]) -> typing.Tuple[list[Bookmark], dict[str, int]]:
    bookmarks = []
    tags = collections.defaultdict(lambda: 0)
    ts = []

    def _(x):
        if isinstance(x, Folder):
            if x.title:
                ts.append(x.title)
            for child in x.children:
                _(child)
            if x.title:
                ts.pop()
        elif paths and not any(x.path.startswith(path) for path in paths):
            return
        else:
            x.tags = set(ts)
            for t in ts:
                tags[t] += 1
            bookmarks.append(x)

    _(folder)
    total = len(bookmarks)
    to_removes = [tag for tag, count in tags.items() if count == total]
    for tag in to_removes:
        del tags[tag]
        for b in bookmarks:
            if tag in b.tags:
                b.tags.remove(tag)

    return bookmarks, tags


def render(bookmarks: list[Bookmark]) -> str:
    tags = collections.defaultdict(lambda: 0)
    for b in bookmarks:
        for t in b.tags:
            tags[t] += 1

    def _(b):
        icon = b.icon_data_uri if b.icon_data_uri else get_svg_uri(b)
        icon_html = f'<img src="{icon}" width="32" height="32" />'

        tags_html = ''.join(f'<div class="tag" data-name="{escape_element(tag)}">{escape_element(tag)}</div>' for tag in b.tags)

        return (
            '<div class="bookmark">'
            f'<a href="{escape_attr_url(b.uri)}" referrerpolicy="no-referrer" target="_blank">'
            f'{icon_html}<p>{escape_element(b.title)}</p></a>'
            f'<div class="tags">{tags_html}</div>'
            '</div>'
        )

    context = {
        'tags': ''.join(
            f'<div class="tag" data-name="{escape_element(n)}"><span>{escape_element(n)}</span><span>{c}</span></div>'
            for n, c in tags.items()),
        'bookmarks': ''.join(_(b) for b in bookmarks)
    }

    return re.sub(r'\{%\s*(\w+)\s*%}', lambda m: context[m.group(1)], HTML_TMPL)


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


def save_bookmarks2sqlite(bookmarks: list[Bookmark], db):
    conn = sqlite3.connect(db)
    bookmark_tuples = [b.to_sqlite_tuple() for b in bookmarks]
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS bookmarks(title, uri, icon_uri, icon_data_uri, tags)")
        conn.executemany("INSERT INTO bookmarks VALUES (?,?,?,?,?)", bookmark_tuples)
    conn.close()


def row2bookmark(row):
    return Bookmark(
        title=row[0],
        uri=row[1],
        parent='',
        icon_uri=row[2],
        icon_data_uri=row[3],
        tags=set(row[4].split(';'))
    )


def load_bookmarks_from_sqlite(db) -> list[Bookmark]:
    conn = sqlite3.connect(db)
    bookmarks = [
        row2bookmark(row) for row in conn.execute("SELECT * FROM bookmarks")
    ]
    conn.close()
    return bookmarks


def add_bookmark2sqlite(bookmark: Bookmark, db):
    conn = sqlite3.connect(db)

    def _check_dup(an):
        rows = conn.execute(f"SELECT * FROM bookmarks where {an}=?", (getattr(bookmark, an), )).fetchall()
        if len(rows) > 0:
            raise ValueError(f"Duplicate for {an}={getattr(bookmark, an)}")

    with conn:
        _check_dup("title")
        _check_dup("uri")
        conn.execute("INSERT INTO bookmarks VALUES (?,?,?,?,?)", bookmark.to_sqlite_tuple())
    conn.close()


def add_bookmark(args):
    bookmark = Bookmark(title=args.title, uri=args.uri, parent='', tags=args.tags)
    get_all_info(bookmark, get_title=True)
    if not bookmark.title:
        bookmark.title = bookmark.uri
    add_bookmark2sqlite(bookmark, args.db)


def print_bookmarks(cur: sqlite3.Cursor | list[tuple[str, str, str, str, str]]):
    for idx, row in enumerate(cur):
        print(f"========== Bookmark.{idx} ===========")
        print(f"title={row[0]}, uri={row[1]}")
        print(f"icon_uri={row[2]}, has_icon_data={bool(row[3])}")
        print(f"tags:", "  ".join(row[4].split(";")))


def remove_bookmark(args):
    conn = sqlite3.connect(args.db)
    key_an = "title" if args.title else "uri"
    with conn:
        cur = conn.execute(f"SELECT * FROM bookmarks WHERE {key_an}=?", (getattr(args, key_an),))
        bookmarks = cur.fetchall()
        if len(bookmarks) < 1:
            print('Nothing to remove')
        else:
            print_bookmarks(bookmarks)
            print("=" * 80)
            if not args.yes and input(f'Do you want to remove?[Yy/Nn]').lower() != 'y':
                print("Won't remove")
            else:
                cur = conn.execute(f"DELETE FROM bookmarks WHERE {key_an}=?", (getattr(args, key_an),))
                print(cur.rowcount, 'deleted')
    conn.close()


def update_icon(args):
    bookmarks = load_bookmarks_from_sqlite(args.db)
    get_all_info(bookmarks, icon_cache_dir=args.icon_cache_dir, force=True)
    conn = sqlite3.connect(args.db)
    with conn:
        for bookmark in bookmarks:
            if not bookmark.icon_updated:
                continue
            logger.info(f"{bookmark.title}({bookmark.uri}) icon updated")
            conn.execute("UPDATE bookmarks SET icon_data_uri=? WHERE uri =?", (bookmark.icon_data_uri, bookmark.uri))
    conn.close()


def query_bookmark(args):
    conn = sqlite3.connect(args.db)
    with conn:
        if args.title:
            cur = conn.execute("SELECT * FROM bookmarks WHERE title like ?", (f"%{args.title}%", ))
        else:
            cur = conn.execute("SELECT * FROM bookmarks WHERE uri like ?", (f"%{args.uri}%", ))
        print_bookmarks(cur)
    conn.close()


def modify_bookmark(args):
    conn = sqlite3.connect(args.db)
    key_an = "title" if args.title else "uri"
    with conn:
        cur = conn.execute(f"SELECT * FROM bookmarks WHERE {key_an}=?", (getattr(args, key_an),))
        bookmarks = [row2bookmark(row) for row in cur]
        assert len(bookmarks) == 1
        updates = {}
        if args.icon_uri:
            for b in bookmarks:
                b.icon_uri = args.icon_uri
            get_all_info(bookmarks)
            if bookmarks[0].icon_updated:
                updates['icon_data_uri'] = bookmarks[0].icon_data_uri
                updates['icon_uri'] = args.icon_uri
        if args.tags:
            updates['tags'] = ';'.join(args.tags)
        elif args.add_tags:
            tags = bookmarks[0].tags
            tags.update(args.add_tags)
            updates['tags'] = ';'.join(tags)
        elif args.remove_tags:
            tags = bookmarks[0].tags
            for tag in set(args.remove_tags):
                tags.remove(tag)
            updates['tags'] = ';'.join(tags)
        if updates:
            set_stat = ",".join(f"{k}=?" for k in updates.keys())
            sql = f"UPDATE bookmarks SET {set_stat} WHERE {key_an}=?"
            parameters = (*updates.values(), getattr(args, key_an))
            logger.debug("sql=%s, parameters=%s", sql, parameters)
            rowcount = conn.execute(sql, parameters).rowcount
            print(rowcount, 'rows updated')
        else:
            print("nothing to update")


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
    parser = argparse.ArgumentParser(add_help=True)
    sub_parser = parser.add_subparsers(dest="action")
    convert_parser = sub_parser.add_parser("convert")
    convert_parser.add_argument('-b', '--browser', dest='browser', required=True, choices=list(browser_mapping.keys()))
    convert_parser.add_argument('db', help='/path/to/db')
    convert_parser.add_argument('-i', dest='input_path', required=False, default=None,
                                help='/path/to/bookmarks/file, if not supplied, the default (across the browser) will be used.')
    convert_parser.add_argument('-p', '--path-filter', metavar='PATH_FILTER', dest='path_filters', default=[], action='append',
                                help='filter bookmarks by path, use "." to split parent and child. apply multiple times works as "OR"')
    convert_parser.add_argument('--skip-empty', dest='skip_empty', action='store_true',
                                help='skip empty folder')
    convert_parser.add_argument('--icon-cache', dest='icon_cache_dir', default=None,
                                help='use the cache dir for icons')
    convert_parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')
    convert_parser.add_argument('-v', '--verbose', action='count', default=0)

    render_parser = sub_parser.add_parser("render")
    render_parser.add_argument("db", help='/path/to/db')
    render_parser.add_argument("output_path", help='/path/to/the/generate/html')
    render_parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')
    render_parser.add_argument('-v', '--verbose', action='count', default=0)

    query_parser = sub_parser.add_parser("query")
    query_parser.add_argument("db", help='/path/to/db')
    query_key_group = query_parser.add_mutually_exclusive_group(required=True)
    query_key_group.add_argument("--title")
    query_key_group.add_argument("--uri")
    query_parser.add_argument('-v', '--verbose', action='count', default=0)

    add_parser = sub_parser.add_parser("add")
    add_parser.add_argument("db", help="/path/to/db")
    add_parser.add_argument("--title", help="title", required=False)
    add_parser.add_argument("--uri", help="uri", required=True)
    add_parser.add_argument("--tag", metavar='TAG', dest='tags', default=[], action='append', required=True)
    add_parser.add_argument('-v', '--verbose', action='count', default=0)

    remove_parser = sub_parser.add_parser("remove")
    remove_parser.add_argument("db", help="/path/to/db")
    remove_key_group = remove_parser.add_mutually_exclusive_group(required=True)
    remove_key_group.add_argument("--title", help="title")
    remove_key_group.add_argument("--uri", help="uri")
    remove_parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')
    remove_parser.add_argument('-v', '--verbose', action='count', default=0)

    modify_parser = sub_parser.add_parser("modify")
    modify_parser.add_argument("db", help="/path/to/db")
    modify_parser.add_argument("-v", "--verbose", action='count', default=0)
    modify_key_group = modify_parser.add_mutually_exclusive_group(required=True)
    modify_key_group.add_argument("--title", help="title")
    modify_key_group.add_argument("--uri", help="uri")
    modify_value_group = modify_parser.add_argument_group()
    modify_tag_group = modify_value_group.add_mutually_exclusive_group(required=True)
    modify_tag_group.add_argument("--tag", metavar="TAG", dest='tags', default=[], action='append')
    modify_tag_group.add_argument("--add-tag", metavar="TAG", dest='add_tags', default=[], action='append')
    modify_tag_group.add_argument("--remove-tag", metavar="TAG", dest='remove_tags', default=[], action='append')
    modify_value_group.add_argument("--icon-uri")

    update_icon_parser = sub_parser.add_parser("update-icon")
    update_icon_parser.add_argument("db", help="/path/to/db")
    update_icon_parser.add_argument('--icon-cache', dest='icon_cache_dir', default=None,
                                    help='use the cache dir for icons')
    update_icon_parser.add_argument('-v', '--verbose', action='count', default=0)

    args = parser.parse_args()
    logger.setLevel(max(logging.ERROR - 10 * args.verbose, logging.DEBUG))

    if args.action == "convert":
        if args.input_path is None:
            args.input_path = browser_mapping[args.browser]['get_default']()
            logger.info('use default of %s: %s', args.browser, args.input_path)

        if not os.path.exists(args.input_path):
            logger.error('%s does not exist!', args.input_path)
            sys.exit(1)

        if args.icon_cache_dir and not os.path.isdir(args.icon_cache_dir):
            logger.error('%s is not a directory!', args.icon_cache_dir)
            sys.exit(1)

        if os.path.exists(args.db):
            logger.warning('%s exists!', args.db)
            if not args.yes and input(f'Do you want to append "{args.db}"?[Yy/Nn]').lower() != 'y':
                sys.exit(1)

        folder = browser_mapping[args.browser]['loader'](args.input_path, args.skip_empty)
        get_all_info(folder, args.path_filters, args.icon_cache_dir)
        bookmarks, _ = convert2list_with_tags(folder, args.path_filters)
        save_bookmarks2sqlite(bookmarks, args.db)
    elif args.action == "render":
        if os.path.exists(args.output_path):
            logger.warning('%s exists!', args.output_path)
            if not args.yes and input(f'Do you want to overwrite "{args.output_path}"?[Yy/Nn]').lower() != 'y':
                sys.exit(1)
        with open(args.output_path, 'w+') as of:
            bookmarks = load_bookmarks_from_sqlite(args.db)
            html = render(bookmarks)
            of.write(html)
    elif args.action == "query":
        query_bookmark(args)
    elif args.action == "add":
        add_bookmark(args)
    elif args.action == "remove":
        remove_bookmark(args)
    elif args.action == "modify":
        modify_bookmark(args)
    elif args.action == "update-icon":
        update_icon(args)


HTML_TMPL = '''<html lang="zh-CN">
    <head>
        <meta charset="UTF-8" />
        <title>Bookmarks</title>
        <style>
            .tags {
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 1vw;
            }
            .tags > .tag {
                background: #a3d2ff;
            }
            .tag.active {
                background: #ffa3d2;
            }
            .tag > span + span::before {
                content: "(";
            }
            .tag > span + span::after {
                content: ")";
            }
            .bookmarks {
                margin-top: 3vh;
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                grid-gap: 1vw;
            }
            .bookmark {
                grid-auto-rows: max-content;
                display: grid;
                grid-template-columns: 64px 1fr;
            }
            .bookmark.inactive {
                display: none;
            }
            .bookmark > a {
                grid-column: 1 / 3;
                grid-row: 1 / 3;
            }
            .bookmark .tags {
                justify-content: left;
                grid-column: 2;
                grid-row: 1;
            }
            .bookmark p {
                word-wrap: anywhere;
            }
        </style>
    </head>
    <body>
        <div class="tags nav">
        {% tags %}
        </div>
        <div class="bookmarks">
        {% bookmarks %}
        </div>
    <script>
        var tag_clicked = false;
        function clickTag(e) {
            if (tag_clicked) {
                return;
            }
            tag_clicked = true;
            let ele = e.target;
            while (!ele.dataset.hasOwnProperty('name')) {
                ele = ele.parentElement;
            }
            let tag = ele.dataset.name;
            let activate = !ele.classList.contains('active');
            for (let other_tag_e of document.querySelectorAll('.nav .tag')) {
                other_tag_e.classList.remove('active');
                if (activate && other_tag_e.dataset.name == tag) {
                    other_tag_e.classList.add('active');
                }
            }
            if (activate) {
                ele.classList.add('active');
            }
            for (let bookmark of document.querySelectorAll('.bookmark')) {
                let active_bookmark_tag = bookmark.querySelector(`[data-name="${tag}"]`);
                for (let bookmark_tag of bookmark.querySelectorAll('.tag')) {
                    bookmark_tag.classList.remove('active');
                }
                if (!activate) {
                    bookmark.classList.remove('inactive');
                } else if (active_bookmark_tag) {
                    active_bookmark_tag.classList.add('active');
                    bookmark.classList.remove('inactive');
                } else {
                    bookmark.classList.add('inactive');
                }
            }
            tag_clicked = false;
        };
        (function () {
            for (let e of document.querySelectorAll('.tag')) {
                e.addEventListener('click', clickTag);
            }
        })();
    </script>
    </body>
</html>'''


if __name__ == "__main__":
    main()
