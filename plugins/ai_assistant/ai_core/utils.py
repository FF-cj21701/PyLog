
import json
import re

def extract_code(text):
    if not text:
        return ""
    if "```" not in text:
        return text.strip()
    parts = text.split("```")
    if len(parts) < 3:
        return text.strip()
    block = parts[1]
    if block.lstrip().startswith("python"):
        block = block.lstrip()[6:]
    return block.strip()

def _fix_json_errors(json_str):
    s = json_str.strip()
    
    s = re.sub(r'//.*', '', s)
    s = re.sub(r'#.*', '', s)
    
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*\]", "]", s)
    
    s = re.sub(r"'", '"', s)
    
    s = re.sub(r"(\w+):", r'"\1":', s)
    
    s = re.sub(r'"(\d+)"', r'\1', s)
    
    return s

def _try_parse_json(json_str):
    s = _fix_json_errors(json_str)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    
    try:
        import ast
        return ast.literal_eval(s)
    except:
        pass
    
    return None

def extract_json(text):
    s = text.strip()
    if "```" in s:
        parts = s.split("```")
        for i in range(1, len(parts), 2):
            block = parts[i]
            b = block.lstrip()
            if b.lower().startswith("json"):
                b = b[4:].strip()
            obj = _try_parse_json(b)
            if obj is not None:
                return obj
    obj = _try_parse_json(s)
    if obj is not None:
        return obj
    return None

def extract_json_list(text):
    """Extracts JSON objects representing tool calls or final answers from text."""
    out = []
    if not text:
        return out
        
    s = text.strip()
    
    if "```" in s:
        parts = s.split("```")
        for i in range(1, len(parts), 2):
            b = parts[i].lstrip()
            if b.lower().startswith("json"):
                b = b[4:].strip()
            obj = _try_parse_json(b)
            if obj is not None and isinstance(obj, dict) and ("tool" in obj or "final" in obj):
                out.append(obj)
        if out:
            return out

    start_indices = [m.start() for m in re.finditer(r'\{', s)]
    
    found_end_indices = set()
    
    for st in start_indices:
        if st in found_end_indices: continue
        
        depth = 0
        end = None
        for j in range(st, len(s)):
            ch = s[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        
        if end:
            frag = s[st:end]
            obj = _try_parse_json(frag)
            if obj is not None and isinstance(obj, dict) and ("tool" in obj or "final" in obj):
                out.append(obj)
                for k in range(st, end):
                    found_end_indices.add(k)
                
    if not out:
        text_without_plan = re.sub(r'^.*?(?=\{|\[)', '', s, count=1)
        if text_without_plan != s:
            start_indices = [m.start() for m in re.finditer(r'\{', text_without_plan)]
            for st in start_indices:
                if st in found_end_indices: continue
                depth = 0
                end = None
                for j in range(st, len(text_without_plan)):
                    ch = text_without_plan[j]
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end = j + 1
                            break
                if end:
                    frag = text_without_plan[st:end]
                    obj = _try_parse_json(frag)
                    if obj is not None and isinstance(obj, dict) and ("tool" in obj or "final" in obj):
                        out.append(obj)
                
    return out

def render_html(text):
    if not text:
        return ""
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    blocks = []
    parts = esc.split("```")
    for i, seg in enumerate(parts):
        if i % 2 == 0:
            lines = seg.split("\n")
            html_lines = []
            in_ul = False
            for ln in lines:
                if ln.startswith("#"):
                    level = min(len(ln.split(" ")[0]), 6)
                    html_lines.append(f"<h{level}>{ln.lstrip('#').strip()}</h{level}>")
                else:
                    html_lines.append(f"<p>{ln}</p>")
            blocks.append("\n".join(html_lines))
        else:
            blocks.append(f"<pre><code>{seg}</code></pre>")
    return "\n".join(blocks)
