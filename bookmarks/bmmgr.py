from __future__ import annotations

import abc
import functools
import sqlite3
import sys
import os.path
import io
import fcntl
import argparse
import typing
import zipfile
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
    parent: str = ''
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

    def data_dict(self) -> typing.Dict:
        return {
            "title": self.title,
            "uri": self.uri,
            "icon_uri": self.icon_uri,
            "icon_data_uri": self.icon_data_uri,
            "tags": list(sorted(self.tags))
        }

    @classmethod
    def from_data_dict(cls, data_dict: typing.Dict) -> Bookmark:
        data_dict["tags"] = set(data_dict["tags"])
        return Bookmark(**data_dict)


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
                logger.warning('aio get status: %d, %s', resp.status, b.icon_uri)
                return
            img_type = resp.headers.get('Content-Type')
            if not img_type.startswith("image"):
                logger.warning('aio get unknown type: %s, %s', img_type, b.icon_uri)
                return
            data = base64.b64encode(data).decode()
            if not data:
                logger.warning('aio get finished: %s, but there is no data', b.icon_uri)
                return
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
            if resp.real_url != resp.real_url.__class__(bookmark.uri):
                logger.error('redirection found %s -> %s', bookmark.uri, resp.real_url)
            if resp.status != 200:
                logger.warning('cannot fetch data from %s, got http code: %d', bookmark.uri, resp.status)
                return
            try:
                html = data.decode(resp.charset if resp.charset else "utf-8")
            except UnicodeDecodeError as e:
                logger.warning('catch decode error, try use errors="replace"', exc_info=e)
                html = data.decode(resp.charset if resp.charset else "utf-8", errors="replace")
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
    categorical_tags = collections.defaultdict(lambda: collections.defaultdict(lambda: 0))
    for b in bookmarks:
        for tag in b.tags:
            if ":" in tag:
                category, _ = tag.split(":", maxsplit=1)
            else:
                category = ''
            categorical_tags[category][tag] += 1

    def _(b):
        icon = b.icon_data_uri if b.icon_data_uri else get_svg_uri(b)
        icon_html = f'<img src="{icon}" width="64" height="64" />'

        tags_html = ''.join(f'<div class="tag" data-name="{escape_element(tag)}">{escape_element(tag)}</div>' for tag in sorted(b.tags))

        return (
            '<div class="bookmark">'
            f'<div class="icon">{icon_html}</div>'
            f'<div class="tags">{tags_html}</div>'
            f'<p><a href="{escape_attr_url(b.uri)}" referrerpolicy="no-referrer" target="_blank">{escape_element(b.title)}</a></p>'
            '</div>'
        )

    tag_htmls = []
    for category, tags in sorted(categorical_tags.items(), key=lambda x: x[0]):
        if category:
            tag_htmls.append(f'<details class=""><summary>{category}</summary>')
        tag_htmls.append('<div class="tags">')
        tag_htmls.append(''.join(
            f'<div class="tag" data-name="{escape_element(n)}" data-category="{category}"><span>{escape_element(n)}</span><span>{c}</span></div>'
            for n, c in sorted(tags.items(), key=lambda x: -x[1])
        ))
        tag_htmls.append('</div>')
        if category:
            tag_htmls.append('</details>')


    context = {
        'tags': ''.join(tag_htmls),
        'bookmarks': ''.join(_(b) for b in bookmarks)
    }

    return re.sub(r'\{%\s*(\w+)\s*%}', lambda m: context[m.group(1)], '''<html lang="zh-CN">
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
                color: white;
                padding: 0.2vw;
                cursor: pointer;
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
                gap: 0.3vw;
                grid-template-areas:
                    "a b b b b b"
                    "a c c c c c"
                    "a c c c c c"
                    "a c c c c c";
                align-items: start;
                border: solid 2px;
                border-image: linear-gradient(167deg, rgba(0, 216, 247, 0) 50%, rgba(0, 216, 247, 1) 100%) 2 2 2 2;
                padding: 0.5vw;
            }
            .bookmark:hover {
                border-image: linear-gradient(167deg, rgba(0, 216, 247, 0) 0%, rgba(0, 216, 247, 1) 100%) 2 2 2 2;
                box-shadow: 0.1vw 0.1vw 0.05vw 0.05vw rgba(0, 108, 247, 0.2);
            }
            .bookmark.inactive {
                display: none;
            }
            .bookmark > .icon {
                width: 64px;
                grid-area: a;
            }
            .bookmark .tags {
                justify-self: start;
                grid-area: c;
                justify-content: start;
                gap: 0.1vw;
            }
            .bookmark p {
                margin: 0;
                grid-area: b;
                word-wrap: anywhere;
            }
            .bookmark a {
                text-decoration: none;
                color: rgb(76, 0, 152);
            }
        </style>
    </head>
    <body>
        <div class="nav">
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
                    if (other_tag_e.dataset.hasOwnProperty('category')) {
                        other_tag_e.parentElement.parentElement.open = true;
                    }
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
</html>''')


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


class IStorage(abc.ABC):

    def query(self, dnf: typing.Iterable[typing.Iterable[tuple[str, str, str]]]) -> list[Bookmark]:
        assert isinstance(dnf, (list, tuple))
        assert all(map(lambda x: isinstance(x, (list, tuple)), dnf))
        assert all(op in ("=", "like") for conditions in dnf for _, op, _ in conditions)
        return self._query(dnf)

    @abc.abstractmethod
    def _query(self, dnf: typing.Iterable[typing.Iterable[tuple[str, str, str]]]) -> list[Bookmark]:
        pass

    @abc.abstractmethod
    def save(self, bookmarks: list[Bookmark]):
        ...

    @abc.abstractmethod
    def load(self) -> list[Bookmark]:
        ...

    @abc.abstractmethod
    def add(self, bookmark: Bookmark):
        ...

    @abc.abstractmethod
    def remove(self, uri: str = "", title: str = "") -> list[Bookmark]:
        ...

    @abc.abstractmethod
    def update(self, bookmarks: list[Bookmark], fields: typing.Iterable):
        ...


class SqliteStorage(IStorage):
    def __init__(self, db):
        self._db = db
        self._conn: typing.Optional[sqlite3.Connection] = None

    def _connect(self):
        if self._conn:
            return
        self._conn = sqlite3.connect(self._db)

    def _disconnect(self):
        if not self._conn:
            return
        self._conn.close()
        self._conn = None

    def __enter__(self):
        self._connect()
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._conn.__exit__(exc_type, exc_val, exc_tb)
        self._disconnect()
        return

    def _query(self, dnf: typing.Iterable[typing.Iterable[tuple[str, str, str]]]) -> list[Bookmark]:
        where_sql = "(" + ") OR (".join(
            ("(" + ") AND (".join(f"`{field}` {op} ?" for field, op, _ in conditions) + ")" ) for conditions in dnf
        ) + ")"
        sql = f"SELECT * FROM bookmarks WHERE {where_sql}"
        logger.debug("query sql: %s", sql)
        params = tuple(value for conditions in dnf for _, _, value in conditions)
        with self:
            return [
                self._row2bookmark(row) for row in self._conn.execute(sql, params)
            ]


    def save(self, bookmarks: list[Bookmark]):
        bookmark_tuples = [b.to_sqlite_tuple() for b in bookmarks]
        with self:
            self._conn.execute("CREATE TABLE IF NOT EXISTS bookmarks(title, uri, icon_uri, icon_data_uri, tags)")
            self._conn.executemany("INSERT INTO bookmarks VALUES (?,?,?,?,?)", bookmark_tuples)

    def load(self) -> list[Bookmark]:
        with self:
            return [
                self._row2bookmark(row) for row in self._conn.execute("SELECT * FROM bookmarks")
            ]

    def add(self, bookmark: Bookmark):
        def _check_dup(an):
            rows = self._conn.execute(f"SELECT * FROM bookmarks where {an}=?", (getattr(bookmark, an), )).fetchall()
            if len(rows) > 0:
                raise ValueError(f"Duplicate for {an}={getattr(bookmark, an)}")

        with self:
            _check_dup("title")
            _check_dup("uri")
            self._conn.execute("INSERT INTO bookmarks VALUES (?,?,?,?,?)", bookmark.to_sqlite_tuple())

    def remove(self, uri: str = "", title: str = "") -> list[Bookmark]:
        assert bool(uri) ^ bool(title)
        if title:
            key = title
            key_an = "title"
        else:
            key = uri
            key_an = "uri"
        with self:
            cur = self._conn.execute(f"SELECT * FROM bookmarks WHERE {key_an}=?", (key,))
            bookmarks = [self._row2bookmark(row) for row in cur]
            if len(bookmarks) > 0:
                self._conn.execute(f"DELETE FROM bookmarks WHERE {key_an}=?", (key,))
            return bookmarks

    def update(self, bookmarks: list[Bookmark], fields: typing.Iterable):
        fields = list(fields)
        only_icon = all(map(lambda x: x.startswith("icon"), fields))
        assert "uri" not in fields, "'uri' should not be updated"
        sql = "UPDATE bookmarks SET {} WHERE uri=?".format(
            ",".join(f"{field}=?" for field in fields)
        )

        fields4params = list(fields) + ["uri"]

        def _to_params(b):
            return tuple(map(lambda x: getattr(b, x) if x != "tags" else ";".join(getattr(b, "tags")), fields4params))

        with self:
            for bookmark in bookmarks:
                if only_icon and not bookmark.icon_updated:
                    continue
                if only_icon:
                    logger.info(f"{bookmark.title}({bookmark.uri}) icon updated")
                parameters = _to_params(bookmark)
                cur = self._conn.execute(sql, parameters)
                logger.debug("sql=%s, parameters=%s, rowcount=%d", sql, parameters, cur.rowcount)


    @staticmethod
    def _row2bookmark(row):
        return Bookmark(
            title=row[0],
            uri=row[1],
            parent='',
            icon_uri=row[2],
            icon_data_uri=row[3],
            tags=set(row[4].split(';'))
        )


class JsonlStorage(IStorage):
    def __init__(self, filepath):
        self._filepath = filepath
        self._fd: typing.Optional[io.TextIOBase] = None

    def _open(self):
        if self._fd:
            return
        self._fd = open(self._filepath, "a+")

    def __enter__(self):
        self._open()
        fcntl.lockf(self._fd.fileno(), fcntl.LOCK_EX)
        self._fd.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert self._fd
        fd = self._fd
        self._fd = None
        fcntl.lockf(fd.fileno(), fcntl.LOCK_UN)
        return fd.__exit__(exc_type, exc_val, exc_tb)

    def _query(self, dnf: typing.Iterable[typing.Iterable[tuple[str, str, str]]]) -> list[Bookmark]:
        def _filter(b):
            if not dnf:
                return True
            for conditions in dnf:
                for field, op, value in conditions:
                    matched = True
                    if op == "=":
                        matched = getattr(b, field) == value
                    elif op == "like":
                        assert value[0] == value[-1] == "%"
                        matched = value[1:-1] in getattr(b, field)
                    else:
                        assert False
                    if not matched:
                        logger.debug("%s %s %s not matched: %r", field, op, value, b)
                        break
                else:
                    return True
            return False
        bookmarks_record_dict = {}
        with self:
            self._fd.seek(0, os.SEEK_SET)
            for idx, line in enumerate(self._fd.readlines()):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get('deleted', False):
                    if data['record']['uri'] in bookmarks_record_dict:
                        del bookmarks_record_dict[data['record']['uri']]
                    continue
                if data['record']['uri'] not in bookmarks_record_dict:
                    bookmarks_record_dict[data['record']['uri']] = data['record']
                else:
                    bookmarks_record_dict[data['record']['uri']].update(data['record'])

        bookmarks = []
        for bookmark_record in bookmarks_record_dict.values():
            bookmark = Bookmark.from_data_dict(bookmark_record)
            if not isinstance(bookmark, Bookmark):
                logger.error("%s %d: %s", bookmark)
                continue
            if not _filter(bookmark):
                continue
            bookmarks.append(bookmark)
        return bookmarks

    def save(self, bookmarks: list[Bookmark]):
        self._save(bookmarks, False)

    def _save(self, bookmarks: list[Bookmark], deleted=False):
        with self:
            self._fd.seek(0, os.SEEK_END)
            for bookmark in bookmarks:
                data = {
                    "record": bookmark.data_dict() if not deleted else {'uri': bookmark.uri, 'title': bookmark.title},
                    "deleted": deleted,
                }
                self._fd.write(json.dumps(data) + "\n")

    def load(self) -> list[Bookmark]:
        return self.query([])

    def add(self, bookmark: Bookmark):
        self.save([bookmark])

    def remove(self, uri: str = "", title: str = "") -> list[Bookmark]:
        assert bool(uri) ^ bool(title)
        dnf = [[("title", "=", title)]] if title else [[("uri", "=", uri)]]
        bookmarks = self.query(dnf)
        self._save(bookmarks, True)
        return bookmarks

    def update(self, bookmarks: list[Bookmark], fields: typing.Iterable):
        self._save(bookmarks, False)


class SplitIconJsonlStorage(JsonlStorage):

    def __init__(self, dirpath: str):
        if not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)
        if not os.path.isdir(dirpath):
            raise ValueError("SplitIconJsonl need a director")
        jsonl_path = os.path.join(dirpath, "bookmarks.jsonl")
        icon_zip_path = os.path.join(dirpath, "icons.zip")
        # if not os.path.exists(jsonl_path):
        #     raise ValueError(f"bookmarks.jsonl dose not exist: {jsonl_path}")
        # if not os.path.exists(icon_zip_path):
        #     raise ValueError(f"icons.zip dose not exist: {icon_zip_path}")
        super().__init__(jsonl_path)
        self._icon_zip_path = icon_zip_path

    def _query(self, dnf: typing.Iterable[typing.Iterable[tuple[str, str, str]]]) -> list[Bookmark]:
        bookmarks = super()._query(dnf)
        with zipfile.ZipFile(self._icon_zip_path, "a") as zf:
            for bookmark in bookmarks:
                if bookmark.icon_data_uri:
                    key: str = bookmark.icon_data_uri
                    bookmark.icon_data_uri = zf.read(key).decode('utf-8')
        return bookmarks

    def _save(self, bookmarks: list[Bookmark], deleted=False):
        icon_data_uris: list[str] = []
        with zipfile.ZipFile(self._icon_zip_path, "a") as zf:
            for bookmark in bookmarks:
                icon_data_uris.append(bookmark.icon_data_uri)
                if bookmark.icon_data_uri:
                    key = hashlib.md5(bookmark.uri.encode()).hexdigest()
                    zf.writestr(key, bookmark.icon_data_uri)
                    bookmark.icon_data_uri = key
        try:
            super()._save(bookmarks, deleted)
        finally:
            for icon_data_uri, bookmark in zip(icon_data_uris, bookmarks):
                bookmark.icon_data_uri = icon_data_uri


class NoIconDataJsonlStorage(JsonlStorage):
    def _save(self, bookmarks: list[Bookmark], deleted=False):
        icon_data_uris: list[str] = []
        for bookmark in bookmarks:
            icon_data_uris.append(bookmark.icon_data_uri)
            bookmark.icon_data_uri = ''
        try:
            super()._save(bookmarks, deleted)
        finally:
            for icon_data_uri, bookmark in zip(icon_data_uris, bookmarks):
                bookmark.icon_data_uri = icon_data_uri


def get_storage(path: str):
    if path.endswith(".db"):
        return SqliteStorage(path)
    if path.endswith(".jsonl"):
        return JsonlStorage(path)
    if path.endswith(".njsonl"):
        return NoIconDataJsonlStorage(path)
    if os.path.isdir(path):
        return SplitIconJsonlStorage(path)
    raise ValueError(f"Unsupported storage: {path}")


def add_icon_cache_param(parser) -> typing.Callable[[argparse.Namespace], bool]:
    def _(args):
        if args.icon_cache_dir and not os.path.isdir(args.icon_cache_dir):
            logger.error('%s is not a directory!', args.icon_cache_dir)
            return False
        return True

    parser.add_argument('--icon-cache', dest='icon_cache_dir', default=None,
                            help='use the cache dir for icons')
    return _


def register_add(add_parser):
    add_parser.add_argument('storage', help='/path/to/storage')
    add_parser.add_argument("--title", help="title", required=False)
    add_parser.add_argument("--uri", help="uri", required=True)
    add_parser.add_argument("--tag", metavar='TAG', dest='tags', default=[], action='append', required=True)
    cb = add_icon_cache_param(add_parser)

    def add_bookmark(args):
        if not cb(args):
            sys.exit(1)
        bookmark = Bookmark(title=args.title, uri=args.uri, parent='', tags=args.tags)
        get_all_info(bookmark, icon_cache_dir=args.icon_cache_dir, get_title=True)
        if not bookmark.title:
            bookmark.title = bookmark.uri
        get_storage(args.storage).add(bookmark)

    return add_bookmark


def register_remove(remove_parser):
    remove_parser.add_argument('storage', help='/path/to/storage')
    remove_key_group = remove_parser.add_mutually_exclusive_group(required=True)
    remove_key_group.add_argument("--title", help="title")
    remove_key_group.add_argument("--uri", help="uri")
    remove_parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')
    def remove_bookmark(args):
        bookmarks = get_storage(args.storage).remove(args.uri, args.title)
        logger.info("total %d deleted", len(bookmarks))
        for bookmark in bookmarks:
            logger.info("%s(%s) deleted", bookmark.uri, bookmark.title)
    return remove_bookmark


def register_update_icon(update_icon_parser):
    update_icon_parser.add_argument('storage', help='/path/to/storage')
    cb = add_icon_cache_param(update_icon_parser)

    def update_icon(args):
        if not cb(args):
            sys.exit(1)
        storage = get_storage(args.storage)
        bookmarks = storage.load()
        get_all_info(bookmarks, icon_cache_dir=args.icon_cache_dir, force=True)
        storage.update(bookmarks, fields=["icon_data_uri", "icon_uri"])

    return update_icon


def register_query(query_parser):
    query_parser.add_argument('storage', help='/path/to/storage')
    query_key_group = query_parser.add_mutually_exclusive_group(required=True)
    query_key_group.add_argument("--title")
    query_key_group.add_argument("--uri")
    def query_bookmark(args):
        storage = get_storage(args.storage)
        key_an = "title" if args.title else "uri"
        dnf = [[(key_an, "like", f"%{getattr(args, key_an)}%")]]
        bookmarks = storage.query(dnf)
        for idx, bookmark in enumerate(bookmarks):
            print(f"========== Bookmark.{idx} ===========")
            print(f"title={bookmark.title}, uri={bookmark.uri}")
            print(f"icon_uri={bookmark.icon_uri}, has_icon_data={bool(bookmark.icon_data_uri)}")
            print(f"tags:", "  ".join(sorted(bookmark.tags)))
    return query_bookmark


def register_modify(modify_parser):
    modify_parser.add_argument('storage', help='/path/to/storage')
    modify_key_group = modify_parser.add_mutually_exclusive_group(required=True)
    modify_key_group.add_argument("--title", help="title")
    modify_key_group.add_argument("--uri", help="uri")
    modify_value_group = modify_parser.add_argument_group()
    modify_tag_group = modify_value_group.add_mutually_exclusive_group(required=False)
    modify_tag_group.add_argument("--tag", metavar="TAG", dest='tags', default=[], action='append')
    modify_tag_group.add_argument("--add-tag", metavar="TAG", dest='add_tags', default=[], action='append')
    modify_tag_group.add_argument("--remove-tag", metavar="TAG", dest='remove_tags', default=[], action='append')
    modify_value_group.add_argument("--icon-uri")
    cb = add_icon_cache_param(modify_parser)

    def modify_bookmark(args):
        if not cb(args):
            sys.exit(1)
        key_an = "title" if args.title else "uri"
        dnf = [[(key_an, "like", f"%{getattr(args, key_an)}%")]]
        storage = get_storage(args.storage)
        bookmarks = storage.query(dnf)
        assert len(bookmarks) == 1
        fields = []
        if args.icon_uri:
            for b in bookmarks:
                b.icon_uri = args.icon_uri
            get_all_info(bookmarks, icon_cache_dir=args.icon_cache_dir, force=True)
            if bookmarks[0].icon_updated:
                fields.extend(("icon_data_uri", "icon_uri"))
        if args.tags:
            bookmarks[0].tags = args.tags
            fields.append("tags")
        elif args.add_tags:
            tags = bookmarks[0].tags
            tags.update(args.add_tags)
            fields.append("tags")
        elif args.remove_tags:
            tags = bookmarks[0].tags
            for tag in set(args.remove_tags):
                tags.remove(tag)
            fields.append("tags")
        if fields:
            storage.update(bookmarks, fields)
        else:
            print("nothing to update")

    return modify_bookmark


def register_resave(resave_parser):
    def _(args):
        src = get_storage(args.src)
        dst = get_storage(args.dst)
        dst.save(src.load())

    resave_parser.add_argument("src", help="/path/to/source")
    resave_parser.add_argument("dst", help="/path/to/destination")
    return _


def register_convert(convert_parser):
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

    convert_parser.add_argument('-b', '--browser', dest='browser', required=True, choices=list(browser_mapping.keys()))
    convert_parser.add_argument('storage', help='/path/to/storage')
    convert_parser.add_argument('-i', dest='input_path', required=False, default=None,
                                help='/path/to/bookmarks/file, if not supplied, the default (across the browser) will be used.')
    convert_parser.add_argument('-p', '--path-filter', metavar='PATH_FILTER', dest='path_filters', default=[],
                                action='append',
                                help='filter bookmarks by path, use "." to split parent and child. apply multiple times works as "OR"')
    convert_parser.add_argument('--skip-empty', dest='skip_empty', action='store_true',
                                help='skip empty folder')
    cb = add_icon_cache_param(convert_parser)
    convert_parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')

    def _(args):

        if args.input_path is None:
            args.input_path = browser_mapping[args.browser]['get_default']()
            logger.info('use default of %s: %s', args.browser, args.input_path)

        if not os.path.exists(args.input_path):
            logger.error('%s does not exist!', args.input_path)
            sys.exit(1)

        if not cb(args):
            sys.exit(1)

        if os.path.exists(args.storage):
            logger.warning('%s exists!', args.storage)
            if not args.yes and input(f'Do you want to append "{args.storage}"?[Yy/Nn]').lower() != 'y':
                sys.exit(1)

        folder = browser_mapping[args.browser]['loader'](args.input_path, args.skip_empty)
        get_all_info(folder, args.path_filters, args.icon_cache_dir)
        bookmarks, _ = convert2list_with_tags(folder, args.path_filters)
        get_storage(args.storage).save(bookmarks)

    return _


def register_render(render_parser):
    render_parser.add_argument('storage', help='/path/to/storage')
    render_parser.add_argument("output_path", help='/path/to/the/generate/html')
    render_parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='answer yes for all attentions')
    render_parser.add_argument('-u', '--update-icon', dest='update_icon', action='store_true', help='update icon before render')
    cb = add_icon_cache_param(render_parser)

    def _(args):
        if os.path.exists(args.output_path):
            logger.warning('%s exists!', args.output_path)
            if not args.yes and input(f'Do you want to overwrite "{args.output_path}"?[Yy/Nn]').lower() != 'y':
                sys.exit(1)
        if not cb(args):
            sys.exit(1)
        with open(args.output_path, 'w+') as of:
            storage = get_storage(args.storage)
            bookmarks = storage.load()
            if args.update_icon or isinstance(storage, NoIconDataJsonlStorage):
                get_all_info(bookmarks, icon_cache_dir=args.icon_cache_dir)
            html = render(bookmarks)
            of.write(html)

    return _


def main():
    parser = argparse.ArgumentParser(add_help=True)
    sub_parsers = parser.add_subparsers(dest="action", required=True)
    register_mapping = {
        'convert': register_convert,
        'render': register_render,
        'resave': register_resave,
        'query': register_query,
        'add': register_add,
        'modify': register_modify,
        'remove': register_remove,
        'update-icon': register_update_icon
    }
    for name, register in register_mapping.items():
        sub_parser = sub_parsers.add_parser(name)
        sub_parser.add_argument('-v', '--verbose', action='count', default=0)
        func = register(sub_parser)
        assert callable(func)
        sub_parser.set_defaults(func=func)

    args = parser.parse_args()
    logger.setLevel(max(logging.ERROR - 10 * args.verbose, logging.DEBUG))
    args.func(args)


if __name__ == "__main__":
    main()
