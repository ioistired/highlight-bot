import timeit as _timeit
import math
import sys
import warnings
from dataclasses import dataclass, field
from typing import List

def timeit(stmt, *, setup='pass', repeat=5, number=0, precision=3, globals=None):
    timer = _timeit.Timer(stmt, setup, globals=globals)

    if number == 0:
        number, _ = timer.autorange()

    all_runs = timer.repeat(repeat, number)
    best = min(all_runs) / number
    worst = max(all_runs) / number

    if worst > 4 * best and best > 0 and worst > 1e-6:
        warnings.warn(ResultMayBeCached(best_time=best, worst_time=worst))

    timings = [ dt / number for dt in all_runs]
    average = math.fsum(timings) / len(timings)
    stdev = math.sqrt(math.fsum((x - average) ** 2 for x in timings) / len(timings))

    return TimeitResult(
        stmt=stmt,
        setup=setup,
        timings=timings,
        mean=average,
        runs=repeat,
        loops_per_run=number,
        stdev=stdev)

@dataclass
class TimeitResult:
    stmt: str = field(repr=False)
    setup: str = field(repr=False)
    timings: List[float] = field(repr=False)
    mean: float
    stdev: float
    runs: int
    loops_per_run: int

    def format(self, *, precision=3):
        fmt = "{mean} {pm} {std} per loop (mean {pm} std. dev. of {runs} run{run_plural}, {number} loop{loop_plural} each)"
        pm = '+-'
        if getattr(sys.stdout, 'encoding', None):
            try:
                '±'.encode(sys.stdout.encoding)
            except UnicodeEncodeError:
                pass
            else:
                pm = '±'

        return fmt.format(
            pm=pm,
            runs=self.runs,
            number=self.loops_per_run,
            loop_plural='s' if self.loops_per_run != 1 else '',
            run_plural='s' if self.runs != 1 else '',
            mean=_format_time(self.mean, precision=precision),
            std=_format_time(self.stdev, precision=precision))

    def __str__(self):
        return self.format()

def _format_time(timespan, *, precision=3):
    if timespan >= 60.0:
        parts = [('d', 60*60*24),('h', 60*60),('min', 60), ('s', 1)]
        time = []
        leftover = timespan
        for suffix, length in parts:
            value = int(leftover / length)
            if value > 0:
                leftover = leftover % length
                time.append(f'{value}{suffix}')
            if leftover < 1:
                break
        return ' '.join(time)

    units = ['s', 'ms', 'us', 'ns']
    scaling = [1, 1e3, 1e6, 1e9]

    if timespan > 0.0:
        order = min(-int(math.floor(math.log10(timespan)) // 3), 3)
    else:
        order = 3
    return f"{timespan * scaling[order]:.{precision-1}f} {units[order]}"

class ResultMayBeCachedWarning(UserWarning):
    def __init__(self, *, best_time, worst_time):
        self.best_time = best_time
        self.worst_time = worst_time
        super().__init__(
            f'The slowest run took {worst_time/best_time:0.2f} times longer than the fastest.'
            'This could mean that an intermediate result is being cached.')
