#!/bin/sh


# [nltk_data] Downloading package punkt_tab to /root/nltk_data...
# [nltk_data]   Unzipping tokenizers/punkt_tab.zip.

# https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip

. /etc/network_turbo
uv run install_nltk_data.py
