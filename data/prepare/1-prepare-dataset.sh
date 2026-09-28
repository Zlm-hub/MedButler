#!/bin/sh

## Download from https://gitee.com/songting/cMedQA2
## 原始数据在 ../raw/（question/answer 的 zip 与 csv）

unzip -o ../raw/question.zip -d ../raw
unzip -o ../raw/answer.zip -d ../raw

python prepare_dataset.py