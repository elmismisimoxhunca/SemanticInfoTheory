import re, glob, sys

ADULT_ROLES = {"Mother","Father","Grandmother","Grandfather","Investigator","Teacher","Adult","Caretaker","Visitor","Relative"}

MAIN_TIER_RE = re.compile(r'^\*([A-Za-z0-9]+):\t(.*)$')
ID_RE = re.compile(r'^@ID:\t?(.*)$')

BRACKET_GROUP_RE = re.compile(r'\[[^\]]*\]')
PAREN_PAUSE_RE = re.compile(r'\((?:\.+|\d+(?:\.\d+)?)\)')
DISFLUENCY_PREFIX_RE = re.compile(r'&[-+=]')
COMPOUND_TERM_RE = re.compile(r'\+(?:\.\.\.|//?\.|"/\.|,)')
WS_RE = re.compile(r'[ \t\r\f\v]+')

def clean_utterance(text):
    text = BRACKET_GROUP_RE.sub(' ', text)
    text = PAREN_PAUSE_RE.sub(' ', text)
    text = DISFLUENCY_PREFIX_RE.sub('', text)
    text = COMPOUND_TERM_RE.sub('.', text)
    text = WS_RE.sub(' ', text)
    return text.strip()

def extract_file(fp):
    with open(fp, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', errors='replace')
    lines = text.split('\n')
    code_role = {}
    for line in lines:
        m = ID_RE.match(line)
        if m:
            parts = m.group(1).split('|')
            if len(parts) >= 8:
                code_role[parts[2].strip()] = parts[7].strip()
    adult_codes = {c for c, r in code_role.items() if r in ADULT_ROLES}
    if not adult_codes:
        return []
    out = []
    cur_code = None
    cur_buf = None
    for line in lines:
        m = MAIN_TIER_RE.match(line)
        if m:
            if cur_code is not None and cur_code in adult_codes:
                out.append(clean_utterance(cur_buf))
            cur_code = m.group(1)
            cur_buf = m.group(2)
        elif line.startswith('\t') and cur_code is not None:
            cur_buf += ' ' + line[1:]
        elif line.startswith('%') or line.startswith('@'):
            if cur_code is not None and cur_code in adult_codes:
                out.append(clean_utterance(cur_buf))
            cur_code = None
            cur_buf = None
    if cur_code is not None and cur_code in adult_codes:
        out.append(clean_utterance(cur_buf))
    return [u for u in out if u]

if __name__ == '__main__':
    root = sys.argv[1]
    files = sorted(glob.glob(root + "/**/*.cha", recursive=True))
    total_bytes = 0
    total_utts = 0
    for fp in files:
        utts = extract_file(fp)
        for u in utts:
            total_bytes += len(u.encode('utf-8')) + 1  # +1 for newline separator
        total_utts += len(utts)
    print("files:", len(files))
    print("utterances:", total_utts)
    print("clean_bytes_total:", total_bytes)
    print("required (5*2^23):", 5*2**23)
    print("margin_ratio:", total_bytes / (5*2**23))
