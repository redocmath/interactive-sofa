import re
import json
from collections import defaultdict

def generate_graph_data(tex_filepath):
    # Read the LaTeX file content
    with open(tex_filepath, 'r', encoding='utf-8') as f:
        tex_content = f.read()

    # Regex to match TikZ nodes
    node_pattern = re.compile(
        r'\\node\s*\((?P<id>[a-zA-Z0-9_-]+)\)\s*at\s*\([^)]+\)\s*\[[^\]]*\]\s*\{(?P<label>[^}]+)\};'
    )
    
    # Regex to match TikZ directed edges and capture the drawing options (e.g. dashed, solid)
    link_pattern = re.compile(
        r'\\draw\s*\[(?P<options>[^\]]*)\]\s*\((?P<source>[a-zA-Z0-9_-]+)\).*?\.\.\s*\((?P<target>[a-zA-Z0-9_-]+)\);',
        re.DOTALL
    )

    raw_links = []
    degree_count = defaultdict(int)

    # 1. Parse links and extract line type (solid vs dashed)
    for match in link_pattern.finditer(tex_content):
        options = match.group('options')
        source = match.group('source')
        target = match.group('target')
        
        # Determine the edge type based on TikZ options
        edge_type = "dashed" if "dashed" in options else "solid"
        
        raw_links.append({
            "source": source,
            "target": target,
            "type": edge_type
        })
        
        # Increment the degree count for both the source and target vertices
        degree_count[source] += 1
        degree_count[target] += 1

    raw_nodes = []

    # 2. Parse nodes and assign the calculated degree as the weight
    for match in node_pattern.finditer(tex_content):
        node_id = match.group('id')
        label = match.group('label').strip()
        
        # Infer the node type (e.g., 'def', 'thm', 'lem', 'pro', 'cor', 'rem')
        node_type = node_id.split('_')[0] if '_' in node_id else 'unknown'
        
        raw_nodes.append({
            "id": node_id,
            "type": node_type,
            "label": label,
            "weight": degree_count.get(node_id, 0),
            "proof": ""
        })

    return raw_nodes, raw_links

if __name__ == "__main__":
    nodes, links = generate_graph_data("dep_graph.tex")
    
    # Output nodes
    print("const NODES = [")
    for node in nodes:
        print(f'  {json.dumps(node)},')
    print("];\n")
    
    # Output links
    print("const EDGES = [")
    for link in links:
        print(f'  {json.dumps(link)},')
    print("];")
