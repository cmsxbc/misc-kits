import urllib.request
import json
import os


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


def stats(repo_commits):
    total_additions = 0
    total_deletions = 0
    max_additions = ('', 0)
    max_deletions = ('', 0)
    for repo_key, repo in repo_commits.items():
        for commit in repo['commits']:
            if commit['additions'] > ARTIFACT_LIMIT or commit['deletions'] > ARTIFACT_LIMIT:
                print('skip', commit['commitUrl'])
                continue
            if commit['additions'] > max_additions[1]:
                max_additions = (commit['commitUrl'], commit['additions'])
            if commit['deletions'] > max_deletions[1]:
                max_deletions = (commit['commitUrl'], commit['deletions'])

            total_additions += commit['additions']
            total_deletions += commit['deletions']

    print(f'{max_additions=}, {max_deletions=}')
    print(f'{total_additions=}, {total_deletions=}')


if __name__ == "__main__":
    # repo_commits = get_all_commits()
    # with open('my-data.json', 'w+') as f:
    #     json.dump(repo_commits, f)
    with open('my-data.json') as f:
        stats(json.load(f))
