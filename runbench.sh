#!/bin/bash
# The README's command-line steps 3-5 for the 24 ICRP benchmark cases.
# Step 4 follows the README's multi-core note: several rfluka processes with
# different RANDOMIZ seeds in separate directories, merged with one usbsuw.
#   ./runbench.sh [workers]        default 4
set -u
cd "$(dirname "$0")"
W=${1:-4}
CYCLES=10

python3 make_examples.py || exit 1                    # 3  all installed phantoms
python3 build_exe.py    || exit 1

CASES=""
for s in AM AF 00M 00F 01M 01F 05M 05F 10M 10F 15M 15F; do
  CASES="$CASES ${s}_internal_9500_photon1MeV ${s}_external_photon1MeV"
done

for c in $CASES; do
  d=runs/$c
  [ -f "$d/doses.csv" ] && { echo "== $c: done, skipping"; continue; }
  echo "== $c: $CYCLES cycles on $W workers  $(date)"
  ( cd "$d" || exit 1
    E=""; [ -x flukamrcp ] && E="-e $PWD/flukamrcp"
    w=1; left=$CYCLES
    while [ $w -le $W ] && [ $left -gt 0 ]; do
      n=$(( (CYCLES + W - w) / W )); [ $n -gt $left ] && n=$left
      left=$((left - n))
      mkdir -p "w$w"
      awk -v s=$((10000 + w*7919)) '
        $1=="RANDOMIZ"      {printf "%-10s%10s%10d\n","RANDOMIZ","1.0",s; next}
        substr($0,1,3)=="../" {print "../" $0; next}
        {print}' "$c.inp" > "w$w/$c.inp"
      ( cd "w$w" && rfluka $E -N0 -M$n "$c" > rfluka.log 2>&1 ) &
      w=$((w + 1))
    done
    wait
    got=$(ls w*/"$c"*_fort.21 2>/dev/null | wc -l)
    if [ "$got" -ne $CYCLES ]; then
      echo "== $c: FAILED, $got/$CYCLES cycles; see $d/w*/rfluka.log"; exit 1
    fi
    { ls w*/*_fort.21; echo; echo "${c}_sum"; } | usbsuw     # 4  merge
    printf '%s_sum.bnn\n%s_sum.lis\n\n' "$c" "$c" | usbrea
    [ -f "${c}_sum.lis" ] || { echo "== $c: FAILED, no ${c}_sum.lis"; exit 1; }
    rm -rf w[0-9]*
  ) || exit 1
  sex=${c%%_*}
  python3 read_doses.py "$sex" "$d/${c}_sum.lis" -o "$d/doses.csv" || exit 1  # 5
  echo "== $c: done  $(date)"
done
echo "ALL CASES COMPLETE  $(date)"
