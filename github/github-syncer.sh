#!/bin/bash

set -eu

GITHUB_TOKEN="$(cat token.txt)"
GITHUB_REPO_DIR="/srv/git"
GITHUB_REPO_DIR="."
PER_PAGE=100
PUSH_DELAY=3600

rm -f result_*.json
rm -f pushed.json # repo_names.txt


for (( page=1; ;page++ ))
do
    echo "get page=${page}"
    curl -H "Accept: application/vnd.github+json" -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/user/repos?per_page=${PER_PAGE}&page=${page}" | tee "result_${page}.json"
    res_count="$(jq '. | length' "result_${page}.json")"
    if [[ "$res_count" != "$PER_PAGE" ]];then
        break
    fi
done

echo "prepare pushed.json"
# jq -s -r 'add | .[] | select(.fork == false) | .full_name' result_*.json > repo_names.txt
jq -s 'add | map( select(.fork == false) | {(.full_name): .pushed_at | fromdate}) | add' result_*.json | tee pushed.json


while read -r full_name
do
    echo "====== $full_name ======"
    repo_dir="${GITHUB_REPO_DIR}/${full_name}.git"
    if [[ -e "$repo_dir" ]];then
        echo "fetch $full_name"
        pushed_ts=$(jq ".\"${full_name}\"" pushed.json)
        limit_ts=$(( pushed_ts - PUSH_DELAY ))
        pushd "$repo_dir"
        commit_ts=$(git log -1 --format=%ct)
        author_ts=$(git log -1 --format=%at)
        echo "commit=${commit_ts},author=${author_ts},pushed=${pushed_ts},limit=${limit_ts}"
        if [ $limit_ts -le "$commit_ts" ] && [ $limit_ts -le "$author_ts" ];then
            echo "consider no update, skip"
        else
            git fetch origin "+refs/heads/*:refs/heads/*"
        fi
        popd
    else
        owner_dir="${GITHUB_REPO_DIR}/$(echo "$full_name" | cut -d '/' -f1)"
        echo "clone $full_name"
        mkdir -p "$owner_dir"
        pushd "$owner_dir"
        git clone --bare "git@github.com:${full_name}"
        popd
        if grep -q 'edit this file' "${repo_dir}/description";then
            echo "sync of https://github.com/${full_name}" > "${repo_dir}/description"
        fi
    fi
    echo "-------------------------------------------------------------------------------------------------"
done <<< "$(jq -r 'keys | .[]' pushed.json)"

