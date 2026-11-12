#!/usr/bin/env bash
# Az időről időre frissülő adatfájlok a `data` ágon élnek, egyetlen (mindig felülírt) commitban,
# így a `main` története nem hízik 15 percenként egy 1,5 MB-os fájllal.
#
#   scripts/data_branch.sh pull            a data ág fájljait a munkakönyvtárba hozza
#                                          (ami a data ágon még nincs meg, az a munkakönyvtárban marad)
#   scripts/data_branch.sh push "üzenet"   a fájlokat egy új, előzmény nélküli commitként a data ágra írja;
#                                          kiírja: changed=true|false (változás nélkül nem ír)
#   scripts/data_branch.sh untrack         ha a fájlok még a main ágon vannak, onnan kiveszi őket (egyszeri átállás)
set -euo pipefail

FILES=(
  data/metrics/atm_history.json
  data/metrics/gemini_labels.json
  data/metrics/gemini_budget.json
)
BRANCH=data

remote_has_branch() { git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; }

cmd_pull() {
  if ! remote_has_branch; then
    echo "data ág: még nincs, a munkakönyvtár fájljai maradnak"
    return 0
  fi
  git fetch -q --depth=1 origin "$BRANCH"
  for f in "${FILES[@]}"; do
    if git cat-file -e "FETCH_HEAD:$f" 2>/dev/null; then
      mkdir -p "$(dirname "$f")"
      git show "FETCH_HEAD:$f" > "$f"
      echo "data ág → $f"
    fi
  done
}

cmd_push() {
  local msg="${1:-Adatfrissítés}"
  local idx
  idx=$(mktemp)
  rm -f "$idx"
  local n=0
  for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    local blob
    blob=$(git hash-object -w "$f")
    GIT_INDEX_FILE="$idx" git update-index --add --cacheinfo "100644,$blob,$f"
    n=$((n + 1))
  done
  if [ "$n" -eq 0 ]; then
    echo "changed=false"
    return 0
  fi
  local tree
  tree=$(GIT_INDEX_FILE="$idx" git write-tree)
  rm -f "$idx"
  if remote_has_branch; then
    git fetch -q --depth=1 origin "$BRANCH"
    if [ "$(git rev-parse 'FETCH_HEAD^{tree}')" = "$tree" ]; then
      echo "changed=false"
      return 0
    fi
  fi
  local commit
  commit=$(git commit-tree "$tree" -m "$msg")
  git push -q --force origin "$commit:refs/heads/$BRANCH"
  echo "changed=true"
}

cmd_untrack() {
  local tracked=()
  for f in "${FILES[@]}"; do
    if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then tracked+=("$f"); fi
  done
  [ "${#tracked[@]}" -eq 0 ] && return 0
  remote_has_branch || { echo "data ág nincs, a fájlok a main ágon maradnak"; return 0; }
  git rm -q --cached -- "${tracked[@]}"
  git commit -q -m "Adatfájlok átköltöztetve a data ágra"
  git pull -q --rebase origin main
  git push -q origin HEAD:main
  echo "main: ${#tracked[@]} adatfájl kivéve (a data ágon élnek tovább)"
}

case "${1:-}" in
  pull) cmd_pull ;;
  push) shift; cmd_push "$@" ;;
  untrack) cmd_untrack ;;
  *) echo "használat: $0 pull | push \"üzenet\" | untrack" >&2; exit 2 ;;
esac
