#!/bin/sh

## Download from https://gitee.com/songting/cMedQA2

unzip -o question.zip
unzip -o answer.zip

python prepare_dataset.py