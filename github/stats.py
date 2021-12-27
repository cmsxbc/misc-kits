import typing
import urllib.request
import json
import os
import datetime


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


def _stat_by_dates(commit_by_dates):
    yearly_stats = {
    }

    def _add(s, k, info):
        if k not in s:
            s[k] = {
                'additions': info['additions'],
                'deletions': info['deletions'],
                'day_count': 1,
                'count': info['count']
            }
        else:
            s[k]['additions'] += info['additions']
            s[k]['deletions'] += info['deletions']
            s[k]['count'] += info['count']
            s[k]['day_count'] += 1

    for dt, commit_info in commit_by_dates.items():
        year = dt.strftime('%Y')
        month = dt.strftime('%m')
        _add(yearly_stats, year, commit_info)
        if 'monthly' not in yearly_stats[year]:
            yearly_stats[year]['monthly'] = {}
        _add(yearly_stats[year]['monthly'], month, commit_info)

    def _print(y):
        data = yearly_stats[y]
        print(f'{y}: additions={data["additions"]}, deletions={data["deletions"]}, days={data["day_count"]}, commits={data["count"]}')
        for m in sorted(data['monthly'].keys()):
            m_data = data['monthly'][m]
            print(f'\t{y}-{m}: additions={m_data["additions"]}, deletions={m_data["deletions"]}, days={m_data["day_count"]}, commits={m_data["count"]}')

    for year in sorted(yearly_stats.keys()):
        _print(year)


def stats(repo_commits, timezone: typing.Optional[datetime.timezone] = None,
          start_datetime: typing.Optional[datetime.datetime] = None,
          end_datetime: typing.Optional[datetime.datetime] = None):
    total_additions = 0
    total_deletions = 0
    max_additions = ('', 0)
    max_deletions = ('', 0)
    max_changes = ('', 0)
    commit_by_dates = {}
    for repo_key, repo in repo_commits.items():
        for commit in repo['commits']:
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

            if commit['additions'] > max_additions[1]:
                max_additions = (commit['commitUrl'], commit['additions'])
            if commit['deletions'] > max_deletions[1]:
                max_deletions = (commit['commitUrl'], commit['deletions'])
            changes = commit['additions'] + commit['deletions']
            if changes > max_changes[1]:
                max_changes = (commit['commitUrl'], changes)

            total_additions += commit['additions']
            total_deletions += commit['deletions']

            dt_key = commit_dt.date()
            if dt_key not in commit_by_dates:
                commit_by_dates[dt_key] = {
                    'additions': commit['additions'],
                    'deletions': commit['deletions'],
                    'count': 1
                }
            else:
                commit_by_dates[dt_key]['additions'] += commit['additions']
                commit_by_dates[dt_key]['deletions'] += commit['deletions']
                commit_by_dates[dt_key]['count'] += 1

    print(f'{max_additions=}\n{max_deletions=}\n{max_changes=}')
    print(f'{total_additions=}, {total_deletions=}')
    _stat_by_dates(commit_by_dates)


if __name__ == "__main__":
    # repo_commits = get_all_commits()
    # with open('my-data.json', 'w+') as f:
    #     json.dump(repo_commits, f)
    with open('my-data.json') as f:
        tz = datetime.timezone(datetime.timedelta(hours=0))
        stats(json.load(f), tz, datetime.datetime(2021, 1, 1, tzinfo=tz))
