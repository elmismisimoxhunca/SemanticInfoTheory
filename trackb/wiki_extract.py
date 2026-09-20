import bz2, re, sys, xml.etree.ElementTree as ET

NS = '{http://www.mediawiki.org/xml/export-0.11/}'

TEMPLATE_OPEN = '{{'
TEMPLATE_CLOSE = '}}'

def strip_balanced(text, open_s, close_s):
    out = []
    depth = 0
    i = 0
    n = len(text)
    ol, cl = len(open_s), len(close_s)
    while i < n:
        if text[i:i+ol] == open_s:
            depth += 1
            i += ol
        elif depth > 0 and text[i:i+cl] == close_s:
            depth -= 1
            i += cl
        elif depth == 0:
            out.append(text[i])
            i += 1
        else:
            i += 1
    return ''.join(out)

REF_RE = re.compile(r'<ref[^>]*/>|<ref[^>]*>.*?</ref>', re.DOTALL | re.IGNORECASE)
COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
TABLE_RE = re.compile(r'\{\|.*?\|\}', re.DOTALL)
FILE_LINK_RE = re.compile(r'\[\[(?:File|Image):[^\]]*\]\]', re.IGNORECASE)
WIKILINK_PIPE_RE = re.compile(r'\[\[[^\]|]*\|([^\]]*)\]\]')
WIKILINK_RE = re.compile(r'\[\[([^\]]*)\]\]')
EXTLINK_TEXT_RE = re.compile(r'\[https?://\S+\s+([^\]]*)\]')
EXTLINK_BARE_RE = re.compile(r'\[https?://[^\]]*\]')
BOLDITALIC_RE = re.compile(r"'''''|'''|''")
HEADING_RE = re.compile(r'^=+\s*(.*?)\s*=+\s*$', re.MULTILINE)
HTML_TAG_RE = re.compile(r'<[^>]+>')
MAGICWORD_RE = re.compile(r'__[A-Z]+__')
ENTITY_MAP = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&nbsp;': ' ', '&apos;': "'"}
BLANK_LINES_RE = re.compile(r'\n{3,}')
TRAILING_WS_RE = re.compile(r'[ \t]+\n')

def wikitext_to_prose(text):
    text = strip_balanced(text, '{{', '}}')
    text = strip_balanced(text, '{|', '|}')
    text = COMMENT_RE.sub('', text)
    text = REF_RE.sub('', text)
    text = FILE_LINK_RE.sub('', text)
    text = EXTLINK_TEXT_RE.sub(lambda m: m.group(1), text)
    text = EXTLINK_BARE_RE.sub('', text)
    text = WIKILINK_PIPE_RE.sub(lambda m: m.group(1), text)
    text = WIKILINK_RE.sub(lambda m: m.group(1), text)
    text = HTML_TAG_RE.sub('', text)
    text = BOLDITALIC_RE.sub('', text)
    text = HEADING_RE.sub(lambda m: m.group(1), text)
    text = MAGICWORD_RE.sub('', text)
    for k, v in ENTITY_MAP.items():
        text = text.replace(k, v)
    lines = [TRAILING_WS_RE.sub('\n', l + '\n')[:-1] for l in text.split('\n')]
    text = '\n'.join(l for l in lines if not l.strip().startswith(('*', '#', ';', ':', '|', '!')))
    text = BLANK_LINES_RE.sub('\n\n', text)
    return text.strip()

def iter_pages(bz2_path):
    with bz2.open(bz2_path, 'rb') as f:
        ns_stack = []
        page = {}
        in_page = False
        for event, elem in ET.iterparse(f, events=('start', 'end')):
            tag = elem.tag.replace(NS, '')
            if event == 'start' and tag == 'page':
                in_page = True
                page = {'ns': None, 'title': None, 'id': None, 'redirect': False, 'text': None}
            elif event == 'end' and in_page:
                if tag == 'ns':
                    page['ns'] = elem.text
                elif tag == 'title':
                    page['title'] = elem.text
                elif tag == 'redirect':
                    page['redirect'] = True
                elif tag == 'id' and page.get('id') is None:
                    page['id'] = elem.text
                elif tag == 'text':
                    page['text'] = elem.text or ''
                elif tag == 'page':
                    in_page = False
                    yield page
                    elem.clear()

if __name__ == '__main__':
    import time
    src = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    target = int(sys.argv[3]) if len(sys.argv) > 3 else None
    total_bytes = 0
    n_pages = 0
    n_eligible = 0
    out_f = open(out_path, 'wb') if out_path else None
    t0 = time.time()
    for page in iter_pages(src):
        n_pages += 1
        if page['ns'] != '0' or page['redirect'] or not page['text']:
            continue
        prose = wikitext_to_prose(page['text'])
        if not prose:
            continue
        n_eligible += 1
        data = (prose + '\n\n').encode('utf-8')
        total_bytes += len(data)
        if out_f:
            out_f.write(data)
        if n_pages % 1000 == 0:
            print('progress', n_pages, total_bytes, round(time.time()-t0,1), flush=True)
        if target is not None and total_bytes >= target:
            break
    if out_f:
        out_f.close()
    print('pages_seen:', n_pages)
    print('eligible_article_pages:', n_eligible)
    print('total_prose_bytes:', total_bytes)
    print('required (5*2^23):', 5*2**23)
    print('elapsed_s:', round(time.time()-t0,1))
