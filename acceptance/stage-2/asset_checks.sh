#!/usr/bin/env bash
# S2-I3 asset checks on a stage folder (verifier seat), from R280/R285 and the design
# direction: "copy the ones used into the stage folder together with their LICENSE", and
# everything the service needs at run time ships inside the image.
#   A1 every .woff2 file in the folder is named by a stylesheet, and every font a
#      stylesheet names is in the folder;
#   A2 every folder holding a .woff2 file holds a LICENSE that is the SIL Open Font License;
#   A3 no stylesheet, script or HTML file in the folder names an http(s) URL other than the
#      SVG and XML namespaces.
# usage: bash asset_checks.sh <stage-dir>   (Git Bash or any POSIX shell with grep, find, comm)
set -u
STAGE=${1:?usage: asset_checks.sh <stage-dir>}
passed=0; failed=0
result() { echo "$1 $2 $3"; if [ "$1" = PASS ]; then passed=$((passed+1)); else failed=$((failed+1)); fi; }

named=$(grep -rhoE "url\(\"?'?[^\"')]+\.woff2" "$STAGE" --include='*.css' | sed -E "s/.*\///" | sort -u)
shipped=$(find "$STAGE" -name '*.woff2' -exec basename {} \; | sort -u)
unused=$(comm -13 <(printf '%s\n' "$named") <(printf '%s\n' "$shipped") | grep . | tr '\n' ' ')
absent=$(comm -23 <(printf '%s\n' "$named") <(printf '%s\n' "$shipped") | grep . | tr '\n' ' ')
if [ -z "$shipped" ]; then result FAIL A1_fonts_shipped_are_the_fonts_used "no .woff2 file in $STAGE"
elif [ -n "$unused$absent" ]; then result FAIL A1_fonts_shipped_are_the_fonts_used "unused: [$unused] named but absent: [$absent]"
else result PASS A1_fonts_shipped_are_the_fonts_used "$(printf '%s\n' "$shipped" | wc -l | tr -d ' ') files"; fi

missing=""
for dir in $(find "$STAGE" -name '*.woff2' -exec dirname {} \; | sort -u); do
  grep -qi "SIL OPEN FONT LICENSE" "$dir/LICENSE" 2>/dev/null || missing="$missing ${dir#$STAGE/}"
done
if [ -n "$missing" ]; then result FAIL A2_each_font_folder_has_its_ofl_licence "no OFL LICENSE in:$missing"
else result PASS A2_each_font_folder_has_its_ofl_licence "$(find "$STAGE" -name '*.woff2' -exec dirname {} \; | sort -u | wc -l | tr -d ' ') folders"; fi

offsite=$(grep -rnoE "https?://[^\"' )>]+" "$STAGE" --include='*.css' --include='*.js' --include='*.mjs' --include='*.html' \
  | grep -vE "https?://www\.w3\.org/(2000/svg|1999/xlink|XML/1998/namespace)" | head -5)
if [ -n "$offsite" ]; then result FAIL A3_no_offsite_urls_in_assets "$offsite"
else result PASS A3_no_offsite_urls_in_assets "none"; fi

echo "asset checks: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
