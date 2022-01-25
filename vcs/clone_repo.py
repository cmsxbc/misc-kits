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
        raise ValueError(f"Unsupportted uri: {repo_uri}")
    if not r.scheme and not r.netloc:
        if not r.path.startswith('git@'):
            raise ValueError(f"Unsupportted uri: {repo_uri}")
        if m := re.fullmatch(r'git@(?P<host>[^/:]+):(?P<user_name>[^/]+)/(?P<repo_name>[^/]+?)(\.git|/)?', r.path):
            return Repo(repo_uri, VCS.git, m.group('repo_name'), m.group('user_name'), m.group('host'))
        else:
            raise ValueError(f"Unsupportted uri: {repo_uri}")
    elif r.scheme == 'https':
        if m := re.fullmatch(r'/(?P<user_name>[^/]+)/(?P<repo_name>[^/]+?)(\.git|/)?', r.path):
            return Repo(repo_uri, VCS.git, m.group('repo_name'), m.group('user_name'), r.netloc)
        else:
            raise ValueError(f"Unsupportted uri: {repo_uri}")
    else:
        raise ValueError(f"Unsupportted uri: {repo_uri}")


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


def print_usage():
    print(sys.argv[0], 'repo_uri')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    if len(sys.argv) == 2:
        repo = parse(sys.argv[1])
        clone(repo)
    elif len(sys.argv) == 3:
        if sys.argv[1] != 'move':
            print_usage()
            sys.exit(1)
        move(sys.argv[2])
    else:
        print_usage()
        sys.exit(1)
