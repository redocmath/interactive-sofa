#!/usr/bin/env python3
"""
Build paper_index.js — mapping from graph node id (e.g. "thm_gerver-monotone")
to {num, env, page, stmt} — from the paper's LaTeX source.

Two-stage strategy:
  1. Parse the .tex sources walking \\input chains to extract numbering and
     statement text for every labeled environment.
  2. Run pdflatex on the source to produce main.aux, then overwrite each entry's
     page number with the authoritative value from \\newlabel.

Usage:
    python3 build_index.py /path/to/paper/source /path/to/graph_data.js  \\
                           --output /path/to/paper_index.js

The source directory must contain main.tex (the entry point).
"""
import re, os, json, argparse, subprocess, shutil

ENV_PREFIX = {
    'theorem': 'thm', 'lemma': 'lem', 'corollary': 'cor',
    'proposition': 'pro', 'conjecture': 'cnj',
    'definition': 'def', 'remark': 'rem',
}
ENV_DISPLAY = {v: k.capitalize() for k, v in ENV_PREFIX.items()}
THM_SHARED_ENVS = {'theorem', 'lemma', 'corollary', 'proposition', 'conjecture'}


def read_tex(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def expand_inputs(text, root):
    def repl(m):
        rel = m.group(1).strip()
        if not rel.endswith('.tex'):
            rel = rel + '.tex'
        full = os.path.join(root, rel)
        if os.path.exists(full):
            return '\n' + expand_inputs(read_tex(full), root)
        return ''
    return re.sub(r'\\input\{([^}]+)\}', repl, text)


def clean_statement(latex_body):
    s = latex_body
    s = re.sub(r'%[^\n]*', '', s)
    s = re.sub(r'\\label\{[^}]*\}', '', s)
    s = re.sub(r'\\(auto)?cite[a-z]*\*?(\[[^\]]*\])*\{[^}]*\}', '', s, flags=re.I)
    s = re.sub(r'\\Cref\{[^}]*\}|\\ref\{[^}]*\}|\\eqref\{[^}]*\}', 'X', s)
    s = re.sub(r'\\\(.*?\\\)', '~', s, flags=re.DOTALL)
    s = re.sub(r'\$[^$]*\$', '~', s)
    s = re.sub(r'\\\[.*?\\\]', '~', s, flags=re.DOTALL)
    for cmd in ['emph', 'textbf', 'textit', 'text', 'mathit', 'mathrm']:
        s = re.sub(r'\\' + cmd + r'\{([^{}]*)\}', r'\1', s)
    s = re.sub(r'\\[a-zA-Z]+\*?\{([^{}]*)\}', r'\1', s)
    s = re.sub(r'\\[a-zA-Z]+\*?', '', s)
    return re.sub(r'\s+', ' ', s).strip()


TOKEN_RE = re.compile(
    r'\\(chapter|section|subsection|subsubsection)(\*?)\s*\{|'
    r'\\appendix\b|'
    r'\\begin\{(theorem|lemma|corollary|proposition|conjecture|definition|remark)\}|'
    r'\\end\{(theorem|lemma|corollary|proposition|conjecture|definition|remark)\}|'
    r'\\label\{([^}]+)\}',
    re.MULTILINE,
)


def parse_source(text):
    chapter_no = section_no = thm_counter = def_counter = rem_counter = 0
    in_appendix, appendix_chapter_no, appendix_letter = False, 0, None
    open_env = None
    results = {}
    pos = 0
    while True:
        m = TOKEN_RE.search(text, pos)
        if not m: break
        pos = m.end()
        tok = m.group(0)
        struct_cmd = m.group(1)
        starred = m.group(2) == '*'

        if struct_cmd == 'chapter':
            if not starred:
                if in_appendix:
                    appendix_chapter_no += 1
                    appendix_letter = chr(ord('A') + appendix_chapter_no - 1)
                else:
                    chapter_no += 1
                section_no = thm_counter = def_counter = rem_counter = 0
        elif tok.startswith(r'\appendix'):
            in_appendix = True
            appendix_chapter_no = 0
            section_no = thm_counter = def_counter = rem_counter = 0
        elif struct_cmd == 'section':
            if not starred:
                section_no += 1
                thm_counter = def_counter = rem_counter = 0
        elif struct_cmd in ('subsection', 'subsubsection'):
            pass
        elif tok.startswith(r'\begin'):
            env = m.group(3)
            chap = appendix_letter if in_appendix else str(chapter_no)
            if env in THM_SHARED_ENVS:
                thm_counter += 1; number = f'{chap}.{section_no}.{thm_counter}'
            elif env == 'definition':
                def_counter += 1; number = f'{chap}.{section_no}.{def_counter}'
            elif env == 'remark':
                rem_counter += 1; number = f'{chap}.{section_no}.{rem_counter}'
            else:
                continue
            open_env = {'env': env, 'number': number, 'body_start': pos, 'label': None}
        elif tok.startswith(r'\end'):
            env = m.group(4)
            if open_env and open_env['env'] == env:
                body = text[open_env['body_start']: m.start()]
                stmt = clean_statement(body)
                if open_env['label']:
                    prefix, _, name = open_env['label'].partition(':')
                    if prefix and name:
                        node_id = f'{prefix}_{name}'
                        results[node_id] = {
                            'num': open_env['number'],
                            'env': ENV_DISPLAY[ENV_PREFIX[env]],
                            'stmt': stmt[:240],
                        }
                open_env = None
        elif tok.startswith(r'\label'):
            label = m.group(5)
            if open_env and ':' in label and open_env['label'] is None:
                prefix = label.split(':', 1)[0]
                if prefix in ENV_PREFIX.values():
                    open_env['label'] = label
    return results


def harvest_aux_pages(aux_path):
    """Extract authoritative {label: page} from a compiled main.aux."""
    if not os.path.exists(aux_path): return {}
    with open(aux_path) as f:
        aux = f.read()
    pages = {}
    for label, num, page in re.findall(r'\\newlabel\{([^{}]+)\}\{\{([^{}]*)\}\{([^{}]*)\}', aux):
        if ':' not in label: continue
        prefix, name = label.split(':', 1)
        if prefix not in ENV_PREFIX.values(): continue
        try: page_i = int(page)
        except ValueError: continue
        pages[f'{prefix}_{name}'] = (num, page_i)
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source_dir',  help='Directory containing main.tex')
    ap.add_argument('graph_data',  help='Path to graph_data.js (for ID filtering)')
    ap.add_argument('--output', '-o', default='paper_index.js')
    ap.add_argument('--no-compile', action='store_true',
                    help='Skip pdflatex; use existing main.aux if present.')
    args = ap.parse_args()

    main_tex = os.path.join(args.source_dir, 'main.tex')
    if not os.path.exists(main_tex):
        ap.error(f'No main.tex in {args.source_dir}')

    # Stage 1: parse source for numbering + statements
    print('Parsing LaTeX source…')
    expanded = expand_inputs(read_tex(main_tex), args.source_dir)
    print(f'  Expanded source: {len(expanded):,} chars')
    parsed = parse_source(expanded)
    print(f'  Resolved {len(parsed)} labeled environments')

    # Stage 2: compile (optional) to get authoritative pages
    if not args.no_compile:
        print('Compiling LaTeX (for page numbers)…')
        # If biblatex is missing, stub it out in a copy of main.tex.
        compile_tex = os.path.join(args.source_dir, '_build_index.tex')
        shutil.copy(main_tex, compile_tex)
        with open(compile_tex) as f: src = f.read()
        src = re.sub(r'\\usepackage\[[^\]]*?biber[^\]]*?\]\s*\{biblatex\}',
                     '% biblatex stubbed for index build', src, flags=re.DOTALL)
        src = re.sub(r'\\addbibresource\{[^}]+\}', '% addbibresource stubbed', src)
        src = re.sub(r'\\printbibliography', '% printbibliography stubbed', src)
        with open(compile_tex, 'w') as f: f.write(src)
        env = {**os.environ, 'TEXINPUTS': '.:./images:'}
        subprocess.run(['pdflatex', '-interaction=nonstopmode', '_build_index.tex'],
                       cwd=args.source_dir, env=env, capture_output=True)
        # second pass for refs
        subprocess.run(['pdflatex', '-interaction=nonstopmode', '_build_index.tex'],
                       cwd=args.source_dir, env=env, capture_output=True)
        aux_path = os.path.join(args.source_dir, '_build_index.aux')
    else:
        aux_path = os.path.join(args.source_dir, 'main.aux')

    aux_pages = harvest_aux_pages(aux_path)
    print(f'  Aux pages harvested: {len(aux_pages)} labels')

    # Filter to graph node IDs
    with open(args.graph_data) as f:
        graph_ids = set(re.findall(r'"id":\s*"([a-z]+_[^"]+)"', f.read()))
    print(f'  Graph node ids: {len(graph_ids)}')

    final = {}
    for nid in graph_ids:
        p = parsed.get(nid)
        a = aux_pages.get(nid)
        if not (p or a): continue
        final[nid] = {}
        if a:
            final[nid]['num'] = a[0]
            final[nid]['page'] = a[1]
        elif p:
            final[nid]['num'] = p['num']
        if p:
            final[nid]['env']  = p['env']
            final[nid]['stmt'] = p['stmt']
        elif a:
            # Best effort env from prefix
            prefix = nid.split('_', 1)[0]
            final[nid]['env'] = ENV_DISPLAY.get(prefix, prefix)

    print(f'  Final entries: {len(final)}')
    missing = graph_ids - final.keys()
    if missing:
        print(f'  WARNING: {len(missing)} graph nodes have no source match:')
        for k in sorted(missing)[:8]:
            print('   ', k)

    with open(args.output, 'w') as f:
        f.write('// Auto-generated by build_index.py from LaTeX source + main.aux\n')
        f.write('window.PAPER_INDEX = ')
        json.dump(final, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
