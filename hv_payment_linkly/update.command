cd "$(dirname "${BASH_SOURCE[0]}")"
find ./ \( -name \*.py -o -name \*.xml -o -name \*.js -o -name \*.py \) -exec sed -i '' -e 's/local_hv_/hv_/g' {} \;
