#! /usr/bin/env python3
import sys
import os
import subprocess
import re
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


def clone(repo: Repo):
    dirpath = os.path.join(repo.host, repo.user)
    os.makedirs(dirpath, mode=0o700, exist_ok=True)
    if os.path.exists(os.path.join(dirpath, repo.name)):
        raise ValueError(f'Seem duplicate {repo.uri}')
    subprocess.check_call(['git', 'clone', repo.uri], cwd=dirpath)


def parse(repo_uri: str) -> Repo:
    r = urllib.parse.urlparse(repo_uri)
    if not r.path.endswith('.git') and not r.path.startswith('git@') and 'git' not in r.netloc:
        raise ValueError("Only support git yet")
    if r.params or r.query or r.fragment:
        raise ValueError("Unsupportted uri")
    if not r.scheme and not r.netloc:
        if not r.path.startswith('git@'):
            raise ValueError("Unsupportted uri")
        if m := re.fullmatch(r'git@(?P<host>[^/:]+):(?P<user_name>[^/]+)/(?P<repo_name>[^/]+?)(\.git)?', r.path):
            return Repo(repo_uri, VCS.git, m.group('repo_name'), m.group('user_name'), m.group('host'))
        else:
            raise ValueError("Unsupportted uri")
    elif r.scheme == 'https':
        if m := re.fullmatch(r'/(?P<user_name>[^/]+)/(?P<repo_name>[^/]+?)(\.git)?', r.path):
            return Repo(repo_uri, VCS.git, m.group('repo_name'), m.group('user_name'), r.netloc)
        else:
            raise ValueError("Unsupportted uri")
    else:
        raise ValueError('Unsupportted uri')


def print_usage():
    print(sys.argv[0], 'repo_uri')


def main(repo_uri):
    repo = parse(repo_uri)
    clone(repo)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print_usage()
        sys.exit(1)
    main(sys.argv[1])
