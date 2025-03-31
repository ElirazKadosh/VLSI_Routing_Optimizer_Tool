#!/bin/bash

# קביעת נתיב הסקריפט הנוכחי
script_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
geosteiner_dir="$script_dir/../geosteiner-5.3"
tmp_dir="$script_dir/tmp_files"

# יצירת תיקיית tmp_files אם לא קיימת
mkdir -p "$tmp_dir"

# בדיקת קלט
if [ $# -ne 1 ]; then
    echo "Usage: $0 \"[(x1, y1), (x2, y2), ...]\""
    exit 1
fi

input_string=$1

# הסרת סוגריים ורווחים מהקלט ויצירת מערך נקודות
cleaned_input=$(echo "$input_string" | tr -d '[]()' | tr ',' ' ')
read -ra coords <<< "$cleaned_input"

# בדיקת שמספר הקואורדינטות זוגי
if [ $(( ${#coords[@]} % 2 )) -ne 0 ]; then
    echo "Invalid number of coordinates."
    exit 1
fi

# חישוב מספר נקודות
num_points=$(( ${#coords[@]} / 2 ))

# קבצי יציאה
tsp_file="$tmp_dir/points.tsp"
dat_file="$tmp_dir/points.dat"
fsts_file="$tmp_dir/fsts.dat"
solution_ps="$tmp_dir/solution.ps"
rsmt_ps="$tmp_dir/rsmt.ps"

# יצירת points.tsp
{
    echo "NAME: example"
    echo "TYPE: TSP"
    echo "DIMENSION: $num_points"
    echo "EDGE_WEIGHT_TYPE: CEIL_2D"
    echo "NODE_COORD_SECTION"
    for (( i=0; i<num_points; i++ )); do
        x=${coords[$((i*2))]}
        y=${coords[$((i*2+1))]}
        echo "$((i+1)) $x $y"
    done
    echo "EOF"
} > "$tsp_file"

# שלבים
"$geosteiner_dir/lib_points" < "$tsp_file" > "$dat_file"
"$geosteiner_dir/rfst" < "$dat_file" > "$fsts_file"
"$geosteiner_dir/bb" < "$fsts_file" > "$solution_ps"
cat "$geosteiner_dir/prelude.ps" "$solution_ps" > "$rsmt_ps"

# תצוגה גרפית
evince "$rsmt_ps" &

