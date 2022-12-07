#!/bin/bash

set -eu

GITHUB_DOMAIN="${GITHUB_DOMAIN:-github.com}"
GITHUB_TOKEN="${GITHUB_TOKEN:-$(cat token.txt)}"
GITHUB_REPO_DIR="${GITHUB_REPO_DIR:-/srv/git}"
PER_PAGE="${PER_PAGE:-100}"
PUSH_DELAY="${PUSH_DELAY:-3600}"

echo GITHUB_DOMAIN=$GITHUB_DOMAIN
echo GITHUB_TOKEN=$GITHUB_TOKEN
echo GITHUB_REPO_DIR=$GITHUB_REPO_DIR
echo PER_PAGE=$PER_PAGE
echo PUSH_DELAY=$PUSH_DELAY


rm -f result_*.json
rm -f pushed.json description.json


for (( page=1; ;page++ ))
do
    echo "get page=${page}"
    curl -H "Accept: application/vnd.github+json" -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/user/repos?per_page=${PER_PAGE}&page=${page}" | tee "result_${page}.json"
    res_count="$(jq '. | length' "result_${page}.json")"
    if [[ "$res_count" != "$PER_PAGE" ]];then
        break
    fi
done

echo "prepare data"
jq -s 'add | map( select(.fork == false) | {(.full_name): .pushed_at | fromdate}) | add' result_*.json | tee pushed.json
jq -s 'add | map( select(.fork == false) | {(.full_name): .description}) | add' result_*.json | tee description.json

while read -r full_name
do
    echo "====== $full_name ======"
    repo_dir="${GITHUB_REPO_DIR}/${full_name}.git"
    origin_description="$(jq -r ".\"${full_name}\" | select(.)" description.json)"
    if [[ "$origin_description" == "" ]];then
        description="sync of 'https://github.com/${full_name}'"
    else
        description="sync of 'https://github.com/${full_name}': ${origin_description}"
    fi
    if [[ -e "$repo_dir" ]];then
        echo "fetch $full_name"
        # shellcheck disable=SC2012
        if [[ "$(ls -1 "${repo_dir}/objects/pack" | wc -l)" == "0" ]];then
            echo "empty repo, fetch anyway"
            pushd "$repo_dir"
            git fetch origin "+refs/heads/*:refs/heads/*"
        else
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
        fi
        popd
        if grep -q "sync of 'https" "${repo_dir}/description";then
            echo "$description" > "${repo_dir}/description"
        fi
    else
        owner_dir="${GITHUB_REPO_DIR}/$(echo "$full_name" | cut -d '/' -f1)"
        echo "clone $full_name"
        mkdir -p "$owner_dir"
        pushd "$owner_dir"
        git clone --bare "git@${GITHUB_DOMAIN}:${full_name}"
        popd
        if grep -q 'edit this file' "${repo_dir}/description";then
            echo "$description" > "${repo_dir}/description"
        fi
    fi
    echo "-------------------------------------------------------------------------------------------------"
done <<< "$(jq -r 'keys | .[]' pushed.json)"

