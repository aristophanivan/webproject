#!/usr/bin/env sh

# make sure to start from script dir
if [ "$(dirname $0)" != "." ]; then
    cd "$(dirname $0)"
fi

pip install -r requirements.txt --no-warn-script-location
python3 ./main.py