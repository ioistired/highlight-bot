#!/usr/bin/env python3

import os
import re
import unicodedata
from functools import partial

import humanize
import lacbd
import psutil

from inspectable_timeit import timeit

mem_usage = lambda _p=psutil.Process(): humanize.naturalsize(_p.memory_full_info().uss)

print('Before timing anything:', mem_usage())

normalize = partial(unicodedata.normalize, 'NFKC')

with open(os.environ['dict']) as f:
	words = [normalize(word.rstrip()) for word in f]

lacbd_code = 'lacbd.Searcher([(word, None) for word in words])'
regex_code = 're.compile(r"(?s)(?i)\b(?:{})\b".format("|".join(map(re.escape, words))))'

use_lacbd = os.environ.get('use_lacbd') == '1'
print('Using', 'lacbd' if use_lacbd else 're')

print(timeit(lacbd_code if use_lacbd else regex_code, globals=globals()))

print('After timing instantiation:', mem_usage())

if use_lacbd:
	searcher = eval(lacbd_code)
	print(timeit('searcher.search(normalize("cafécafé café café"))', globals=globals()))
else:
	regex = eval(regex_code)
	print(timeit('regex.findall(normalize("cafécafé café café"))', globals=globals()))

print('After timing searching:', mem_usage())
