#! /usr/bin/env python3
import sys
import os
import subprocess
import re
import collections
import dataclasses
import enum
import urllib.parse


class VCS(enum.Enum):
    git = 'git'
    # svn = 'svn'


@dataclasses.dataclass
class Repo:
    uri: str
    vcs: VCS
    name: str
    user: str
    host: str
    sub_path: str = ''


def clone(repo: Repo):
    dirpath = os.path.join(repo.host, repo.sub_path, repo.user) if repo.sub_path else os.path.join(repo.host, repo.user)
    os.makedirs(dirpath, mode=0o700, exist_ok=True)
    if os.path.exists(os.path.join(dirpath, repo.name)):
        raise ValueError(f'Seem duplicate {repo.uri}')
    try_count = 0
    while True:
        try_count += 1
        print(f'Try {try_count} clone {repo}')
        process = subprocess.run(['git', 'clone', repo.uri], cwd=dirpath)
        if process.returncode == 0:
            break


def parse(repo_uri: str, allow_sub_path: bool = False) -> Repo:
    r = urllib.parse.urlparse(repo_uri)
    p: str
    match r:
        case urllib.parse.ParseResult(params=params, query=query, fragment=fragment) if params or query or fragment:
            raise ValueError(f"Nonsupport uri({repo_uri}) with params or query or fragment: {r=!r}")
        case urllib.parse.ParseResult(scheme="", netloc="", path=p) if p.startswith("git@"):
            if m := re.fullmatch(
                    r'git@(?P<host>[^/:]+):(?P<sub_path>.+/)?(?P<user_name>[^/]+)/(?P<repo_name>[^/]+?)(\.git|/)?',
                    p):
                if m.group('sub_path') and not allow_sub_path:
                    raise ValueError(f"uri has sub_path({m.group('sub_path')}), but it's not allowed: {repo_uri}")
                return Repo(repo_uri, VCS.git, m.group('repo_name'), m.group('user_name'), m.group('host'),
                            m.group('sub_path'))
        case urllib.parse.ParseResult(scheme="", netloc="", path=p) if p:
            if p.count('/') != 1:
                raise ValueError(f"Unknown uri({repo_uri}) with only path: {p}")
            user_name, repo_name = p.split("/")
            return Repo(f"https://github.com/{user_name}/{repo_name}.git", VCS.git, repo_name, user_name, "github.com")
        case urllib.parse.ParseResult(scheme="https", netloc=netloc, path=p) if netloc and (p.endswith(".git") or "git" in netloc):
            netloc: str
            if m := re.fullmatch(r'(/(?P<sub_path>.+))?/(?P<user_name>[^/]+)/(?P<repo_name>[^/]+?)(\.git|/)?', p):
                if m.group('sub_path') and not allow_sub_path and r.netloc != "gitlab.com":
                    raise ValueError(f"uri has sub_path({m.group('sub_path')}), but it's not allowed: {repo_uri}")
                return Repo(repo_uri, VCS.git, m.group('repo_name'), m.group('user_name'), netloc, m.group('sub_path'))
    raise ValueError(f"Unknown uri({repo_uri}): {r=!r}")


def move(path: str):
    if not os.path.exists(path):
        raise ValueError(f"{path} does not exist!")
    if not os.path.isdir(path):
        raise ValueError(f"{path} is nor directory!")
    remote = subprocess.check_output(['git', 'remote'], cwd=path).decode().strip()
    remote_uri = subprocess.check_output(['git', 'remote', 'get-url', remote], cwd=path).decode().strip()
    repo = parse(remote_uri)
    repo_target_dir = os.path.join(repo.host, repo.user)
    if os.path.relpath(repo_target_dir, path) == '..':
        raise ValueError(f"{path} is already in correct location")
    repo_target = os.path.join(repo_target_dir, repo.name)
    if os.path.exists(repo_target):
        raise ValueError(f"Duplicated!! {repo_target} has existed!")
    os.makedirs(repo_target_dir, mode=0o700, exist_ok=True)
    origin_repo_name = os.path.basename(path)
    if origin_repo_name != repo.name:
        print(f'[WARN] will change dir name from {origin_repo_name} to {repo.name}')
    subprocess.check_call(['mv', path, repo_target])


def update(path: str):
    try_count = 0
    while True:
        try_count += 1
        print(f'Try {try_count} update {path}')
        process = subprocess.run(['git', 'pull'], cwd=path)
        if process.returncode == 0:
            break


def update_all(max_depth=3):
    Item = collections.namedtuple("Item", ("path", "depth"))
    dir_items = [Item(".", 0)]
    while dir_items:
        item = dir_items.pop()
        git_dir = os.path.join(item.path, ".git")
        if os.path.exists(git_dir) and os.path.isdir(git_dir):
            update(item.path)
        elif item.depth < max_depth:
            for sub_dir in os.listdir(item.path):
                dir_items.append(Item(os.path.join(item.path, sub_dir), item.depth + 1))
        else:
            print(f"skip {item=}")


def print_usage():
    print(sys.argv[0], '[ [clone] [--allow-sub-path] | move ] repo_uri|path')


if __name__ == '__main__':
    match sys.argv[1:]:
        case ('update-all' | 'update_all', ):
            update_all()
        case ('--allow-sub-path', str(repo_uri)) | ('clone', '--allow-sub-path', str(repo_uri)):
            repo = parse(repo_uri, True)
            clone(repo)
        case [str(repo_uri)] | ('clone', str(repo_uri)):
            repo = parse(repo_uri)
            clone(repo)
        case ('move', str(path)):
            move(path)
        case _:
            print_usage()
            sys.exit(1)
