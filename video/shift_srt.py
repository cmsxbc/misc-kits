import re
import sys


REGEX = re.compile(
    r'(?P<sh>\d{2}):(?P<sm>\d{2}):(?P<ss>\d{2}),(?P<sms>\d{3})'
    r'(?P<link>\s+-->\s+)'
    r'(?P<eh>\d{2}):(?P<em>\d{2}):(?P<es>\d{2}),(?P<ems>\d{3})'
)


def gen_replace_func(delta):

    def _t(m, p):
        milliseconds = int(m[p+'h']) * 3600_000 + int(m[p+'m']) * 60_000 + int(m[p+'s']) * 1000 + int(m[p+'ms'])
        milliseconds += delta
        nh = milliseconds // 3600_000
        nm = milliseconds % 3600_000 // 60_000
        ns = milliseconds % 60_000 // 1000
        nms = milliseconds % 1000
        return f'{nh:0>2d}:{nm:0>2d}:{ns:0>2d},{nms:0>3d}'

    def _(m):
        return f"{_t(m, 's')}{m['link']}{_t(m, 'e')}"

    return _


def replace_lines(lines, delta):
    no = 0
    for line in lines:
        if no != 1:
            yield line
        else:
            yield REGEX.sub(gen_replace_func(delta), line)
        no += 1
        if not line.strip():
            no = 0


def parse_shift(shift):
    cs = {
        'h': (0, 99, 3600_000),
        'm': (0, 59, 60_000),
        's': (0, 59, 1000),
        'ms': (0, 999, 1)
    }
    sign = 1
    if shift[0] == '-':
        sign = -1
        shift = shift[1:]

    def _(**kwargs):
        delta = 0
        for k, v in kwargs.items():
            if k == 'ms':
                v = v.ljust(3, '0')
            v = int(v)
            b, e, r = cs[k]
            if b <= v <= e:
                delta += v * r
            else:
                raise ValueError(f"{k}={v} not in [{b}, {e}]")
        return delta

    def _sms(*, s, ms='0'):
        ms = ms.ljust(3, '0')
        if not (cs['ms'][0] <= int(ms) <= cs['ms'][1]):
            raise ValueError(f"ms={ms} not in [{cs['ms'][0]}, {cs['ms'][1]}]")
        return int(s) * cs['s'][2] + int(ms)

    match re.split(r'([:.])', shift):
        case [h, ':', m, ':', s, '.', ms]:
            delta = _(h=h, m=m, s=s, ms=ms)
        case [h, ':', m, ':', s]:
            delta = _(h=h, m=m, s=s)
        case [m, ':', s, '.', ms]:
            delta = _(m=m, s=s, ms=ms)
        case [m, ':', s]:
            delta = _(m=m, s=s)
        case [s, '.', ms]:
            delta = _sms(s=s, ms=ms)
        case [s]:
            delta = _sms(s=s)
        case _:
            raise ValueError(f"invalid {shift=}")
    return delta * sign


def test_shift():
    assert parse_shift("5") == 5000
    assert parse_shift("12") == 12000
    assert parse_shift("0.1") == 100
    assert parse_shift("0.12") == 120
    assert parse_shift("0.123") == 123
    assert parse_shift("0.01") == 10
    assert parse_shift("0.001") == 1
    assert parse_shift("11:20") == 680000
    assert parse_shift("11:20.001") == 680001
    assert parse_shift("1:0:0") == 3600_000
    assert parse_shift("1:00:00") == 3600_000
    assert parse_shift("61") == 61_000
    assert parse_shift("61.235") == 61_235

    for t in ("1.0:0", "1:00:00:00", "1:61", "1:61.236", ".999", ".1", "0.1000", "60:00", "100:00:00"):
        try:
            parse_shift(t)
        except ValueError:
            pass
        else:
            assert False, f"No ValueError raised: {t}"


if __name__ == "__main__":
    match sys.argv:
        case (_, source, target, shift):
            with open(source) as f, open(target, 'w+') as of:
                of.writelines(replace_lines(f.readlines(), parse_shift(shift)))
        case _:
            print(f"usage: {sys.argv[0]} source target shift")
            sys.exit(1)
