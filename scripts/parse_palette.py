# -*- coding: utf-8 -*-
"""Parse colors.js from pindou.skin into a structured JSON palette file.
Robust brace-matching parser."""
import re, json

with open('colors.js', encoding='utf-8', errors='ignore') as f:
    t = f.read()

# Find the const palettes = { ... } body
start = t.find('palettes = {')
assert start != -1
start = t.index('{', start)
# brace matching from start
depth = 0
for i in range(start, len(t)):
    if t[i] == '{': depth += 1
    elif t[i] == '}':
        depth -= 1
        if depth == 0:
            end = i
            break
body = t[start + 1:end]

def find_top_keys(body):
    """Return list of (key, content) at depth 0."""
    # scan for key: { at depth 0
    out = []
    depth = 0
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == '{':
            depth += 1; i += 1; continue
        if c == '}':
            depth -= 1; i += 1; continue
        if c == "'":
            # skip string
            j = i + 1
            while j < n and body[j] != "'":
                if body[j] == '\\': j += 1
                j += 1
            i = j + 1
            continue
        if depth == 0 and (c == ',' or c == ' ' or c == '\n' or c == '\t' or c == '\r'):
            i += 1
            continue
        if depth == 0:
            # start of a key
            j = i
            while j < n and (body[j].isalnum() or body[j] == '_'):
                j += 1
            key = body[i:j]
            # skip to colon and brace
            k = j
            while k < n and body[k] != ':': k += 1
            k += 1
            while k < n and body[k] != '{':
                # could be name:'...', skip string
                if body[k] == "'":
                    kk = k + 1
                    while kk < n and body[kk] != "'":
                        if body[kk] == '\\': kk += 1
                        kk += 1
                    k = kk + 1
                else:
                    k += 1
            if k < n:
                # find matching close
                d2 = 1
                m = k + 1
                while m < n:
                    ch = body[m]
                    if ch == '{': d2 += 1
                    elif ch == '}':
                        d2 -= 1
                        if d2 == 0: break
                    elif ch == "'":
                        mm = m + 1
                        while mm < n and body[mm] != "'":
                            if body[mm] == '\\': mm += 1
                            mm += 1
                        m = mm
                    m += 1
                out.append((key, body[k:m]))
                i = m + 1
                continue
        i += 1
    return out

# series color pattern
def parse_series(content):
    """Parse a series block: { name:'..', icon:'..', color:'..', colors:[ {name,hex}, ... ] }"""
    name = re.search(r"name:\s*'([^']*)'", content)
    colors = re.findall(r"\{name:\s*'([^']+)',\s*hex:\s*'(#[0-9A-Fa-f]{6})'\}", content)
    return (name.group(1) if name else ''), colors

result = {}
for top_key, top_content in find_top_keys(body):
    # top_content = { name:..., info:..., series: { S: {...}, ... } }
    series_block = re.search(r"series:\s*(\{)", top_content)
    if not series_block:
        continue
    sb_start = series_block.start(1)
    # brace match from there
    depth = 0
    for i in range(sb_start, len(top_content)):
        if top_content[i] == '{': depth += 1
        elif top_content[i] == '}':
            depth -= 1
            if depth == 0:
                sb_end = i
                break
    series_body = top_content[sb_start + 1:sb_end]
    series = {}
    for s_key, s_content in find_top_keys(series_body):
        name, colors = parse_series(s_content)
        series[s_key] = {'name': name, 'colors': colors}
    result[top_key] = series

with open('bead_palettes.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=1)

total = 0
for k, v in result.items():
    c = sum(len(s['colors']) for s in v.values())
    total += c
    print(f'{k}: {len(v)} series, {c} colors')
print('GRAND TOTAL:', total)
