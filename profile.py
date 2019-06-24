#!/usr/bin/env python3

import os
import re
import sys

import lacbd
import psutil

if len(sys.argv) == 1:
	print('Usage:', sys.argv[0], '<dictionary filename> | psql highlight')
	sys.exit(1)

print(psutil.Process().memory_full_info().uss)

with open() as f:
	if os.environ.get('use_lacbd') == '1':
		searcher = lacbd.Searcher([(s.rstrip(), None) for s in f])
	else:
		regex = re.compile(r'(?i)\b(?:{})\b'.format('|'.join(re.escape(s.rstrip()) for s in f)))

print(psutil.Process().memory_full_info().uss)
