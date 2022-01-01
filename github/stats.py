import typing
import urllib.request
import json
import os
import datetime
import functools


GITHUB_API_GRAPHQL = 'https://api.github.com/graphql'
TOKEN = os.environ['GITHUB_TOKEN']
ARTIFACT_LIMIT = 1000


QUERY_GET_REPOS = """
query {{
  rateLimit {{
    limit
    cost
    remaining
    resetAt
  }},
  viewer {{
    id,
    repositoriesContributedTo (first: 100, contributionTypes: [COMMIT], includeUserRepositories: true {after}) {{
      nodes {{
        name,
        owner {{
          login
        }}
      }},
      pageInfo {{
        endCursor,
        hasNextPage
      }},
      totalCount
    }}
  }}
}}
"""


QUERY_GET_COMMITS_BY_REPO = """
query {{
  rateLimit {{
    limit
    cost
    remaining
    resetAt
  }},
  repository (name: "{repo_name}", owner: "{repo_owner}") {{
    isPrivate,
    defaultBranchRef {{
      target {{
        ... on Commit {{
          history(first: 100, author: {{id: "{author_id}"}} {after}) {{
            nodes {{
              commitUrl,
              deletions,
              additions,
              author {{
                user {{
                  login
                }},
                email,
                name,
              }},
              changedFiles,
              committedDate,
              pushedDate,
            }},
            pageInfo {{
              hasNextPage,
              endCursor
            }},
            totalCount
          }}
        }}
      }}
    }}
  }}
}}
"""


def do_graphql_query(query):
    data = json.dumps({'query': query})
    request = urllib.request.Request(GITHUB_API_GRAPHQL, data=data.encode(), method='POST')
    request.add_header('Authorization', f'bearer {TOKEN}')
    with urllib.request.urlopen(request) as f:
        content = f.read()
    return json.loads(content.decode())


def get_all_commits():
    after = ''
    repo_commits = {}
    while True:
        repo_rsp = do_graphql_query(QUERY_GET_REPOS.format(after=after))
        print(repo_rsp)
        author_id = repo_rsp['data']['viewer']['id']
        for repo_node in repo_rsp['data']['viewer']['repositoriesContributedTo']['nodes']:
            repo_key = f"{repo_node['owner']['login']}/{repo_node['name']}"
            repo_commits[repo_key] = {
                'owner': repo_node['owner']['login'],
                'name': repo_node['name'],
                'isPrivate': True,
                'commits': []
            }
            commit_after = ''
            while True:
                commit_rsp = do_graphql_query(QUERY_GET_COMMITS_BY_REPO.format(
                    author_id=author_id, after=commit_after,
                    repo_owner=repo_node['owner']['login'], repo_name=repo_node['name']))
                print(commit_rsp)
                repo_commits[repo_key]['isPrivate'] = commit_rsp['data']['repository']['isPrivate']
                repo_commits[repo_key]['commits'].extend(
                    commit_rsp['data']['repository']['defaultBranchRef']['target']['history']['nodes'])

                commit_page_info = commit_rsp['data']['repository']['defaultBranchRef']['target']['history']['pageInfo']
                if not commit_page_info['hasNextPage']:
                    break
                else:
                    commit_after = f', after: "{commit_page_info["endCursor"]}"'

        repo_page_info = repo_rsp['data']['viewer']['repositoriesContributedTo']['pageInfo']
        if not repo_page_info['hasNextPage']:
            break
        else:
            after = f', after: "{repo_page_info["endCursor"]}"'
    return repo_commits


def container_add(container, k, commit, custom_key=None):
    if k not in container:
        container[k] = {
            'additions': commit['additions'],
            'deletions': commit['deletions'],
            'count': commit.get('count', 1)
        }
        if custom_key:
            container[k][custom_key] = 1
    else:
        container[k]['additions'] += commit['additions']
        container[k]['deletions'] += commit['deletions']
        container[k]['count'] += commit.get('count', 1)
        if custom_key:
            container[k][custom_key] += 1


def _stat_by_dates(commit_by_dates):
    yearly_stats = {}
    week_stats = {}

    _add = functools.partial(container_add, custom_key='day_count')
    dt: datetime.date
    one_day = datetime.timedelta(1)
    max_allow_rest = 8
    last_dt = None
    streaks = {r: 0 for r in range(max_allow_rest)}
    max_streaks = {r: 0 for r in range(max_allow_rest)}
    longest_rest = 0
    for dt in sorted(commit_by_dates.keys()):
        commit_info = commit_by_dates[dt]
        longest_rest = max(longest_rest, (dt - last_dt).days if last_dt else 0)
        for r in range(max_allow_rest):
            if not last_dt:
                streaks[r] = 1
            elif dt > last_dt + one_day * (r+1):
                max_streaks[r] = max(max_streaks[r], streaks[r])
                streaks[r] = 1
            else:
                streaks[r] += 1
        year = dt.strftime('%Y')
        month = dt.strftime('%m')
        week = dt.strftime('%A')
        _add(yearly_stats, year, commit_info)
        _add(week_stats, week, commit_info)
        if 'monthly' not in yearly_stats[year]:
            yearly_stats[year]['monthly'] = {}
        _add(yearly_stats[year]['monthly'], month, commit_info)
        last_dt = dt

    max_streaks = {r: max(max_streaks[r], streaks[r]) for r in range(max_allow_rest)}

    def _print(y):
        data = yearly_stats[y]
        print(f'{y}: additions={data["additions"]}, deletions={data["deletions"]}, days={data["day_count"]}, commits={data["count"]}')
        for m in sorted(data['monthly'].keys()):
            m_data = data['monthly'][m]
            print(f'\t{y}-{m}: additions={m_data["additions"]}, deletions={m_data["deletions"]}, days={m_data["day_count"]}, commits={m_data["count"]}')

    for year in sorted(yearly_stats.keys()):
        _print(year)

    for week in sorted(week_stats.keys()):
        print(f'{week}, {week_stats[week]}')

    for r in range(max_allow_rest):
        print(f'longest streak-{r}:', max_streaks[r])
    print('longest rest:', longest_rest)


def _stat_by_times(commit_by_times):
    hour_stats = {}
    for t, commit_info in commit_by_times.items():
        hour = t.strftime('%H')
        container_add(hour_stats, hour, commit_info)
    for hour in sorted(hour_stats.keys()):
        print(hour, hour_stats[hour])


def stats(repo_commits, timezone: typing.Optional[datetime.timezone] = None,
          start_datetime: typing.Optional[datetime.datetime] = None,
          end_datetime: typing.Optional[datetime.datetime] = None):
    total_additions = 0
    total_deletions = 0
    max_commits = {
        'additions': {'additions': 0},
        'deletions': {'deletions': 0},
        'changes': {'changes': 0}
    }
    commit_by_dates = {}
    commit_by_times = {}
    by_owner = {}

    _add = container_add

    for repo_key, repo in repo_commits.items():
        if repo['owner'] not in by_owner:
            by_owner[repo['owner']] = {
                'repo_count': 1,
                'count': 0,
                'additions': 0,
                'deletions': 0
            }
        else:
            by_owner[repo['owner']]['repo_count'] += 1
        for commit in repo['commits']:
            commit['changes'] = commit['additions'] + commit['deletions']
            if commit['additions'] > ARTIFACT_LIMIT or commit['deletions'] > ARTIFACT_LIMIT:
                print('skip', commit['commitUrl'])
                continue
            commit_dt = datetime.datetime.strptime(commit['committedDate'], "%Y-%m-%dT%H:%M:%S%z")
            if timezone:
                commit_dt = commit_dt.astimezone(timezone)
            if start_datetime and commit_dt < start_datetime:
                continue
            if end_datetime and commit_dt > end_datetime:
                continue

            max_commits = {k: max_commits[k] if max_commits[k][k] >= commit[k] else commit for k in max_commits.keys()}

            total_additions += commit['additions']
            total_deletions += commit['deletions']

            _add(by_owner, repo['owner'], commit)

            dt_key = commit_dt.date()
            dtt_key = commit_dt.time()
            _add(commit_by_dates, dt_key, commit)
            _add(commit_by_times, dtt_key, commit)

    for k in max_commits.keys():
        print(f'max_{k}={max_commits[k][k]}')
    print(f'{total_additions=}, {total_deletions=}')
    _stat_by_dates(commit_by_dates)
    _stat_by_times(commit_by_times)
    for owner in sorted(by_owner.keys(), key=lambda x: by_owner[x]['count'], reverse=True):
        data = by_owner[owner]
        print(f'{owner}: repos={data["repo_count"]}, commits={data["count"]}, additions={data["additions"]}, deletions={data["deletions"]}')


if __name__ == "__main__":
    # repo_commits = get_all_commits()
    # with open('my-data.json', 'w+') as f:
    #     json.dump(repo_commits, f)
    with open('my-data.json') as f:
        tz = datetime.timezone(datetime.timedelta(hours=0))
        stats(json.load(f), tz, datetime.datetime(2021, 1, 1, tzinfo=tz))
