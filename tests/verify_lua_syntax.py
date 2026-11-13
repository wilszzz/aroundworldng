import re

def verify_lua(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()

    # Pattern to match comments, strings, and block keywords
    pattern = re.compile(
        r'(--\[\[.*?\]\]|--[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\[\[.*?\]\]|\b(?:function|do|repeat|until|if|elseif|else|then|end)\b)',
        re.DOTALL
    )

    stack = []
    tokens = []
    for m in pattern.finditer(code):
        tok = m.group(0)
        if tok.startswith('--') or tok.startswith('"') or tok.startswith("'") or tok.startswith('[['):
            continue
        line_num = code[:m.start()].count('\n') + 1
        tokens.append((tok, line_num))

    errors = []
    for tok, line in tokens:
        if tok in ('do', 'function', 'repeat'):
            stack.append((tok, line))
        elif tok == 'if':
            stack.append(('if', line))
        elif tok == 'then':
            pass # 'if' or 'elseif' is followed by 'then'
        elif tok in ('elseif', 'else'):
            if not stack or stack[-1][0] != 'if':
                errors.append(f"Unexpected '{tok}' at line {line}")
        elif tok == 'end':
            if not stack:
                errors.append(f"Mismatched 'end' at line {line}")
                break
            opener, oline = stack.pop()
            if opener not in ('if', 'do', 'function'):
                errors.append(f"Mismatched 'end' at line {line}, opened by '{opener}' at line {oline}")
        elif tok == 'until':
            if not stack:
                errors.append(f"Mismatched 'until' at line {line}")
                break
            opener, oline = stack.pop()
            if opener != 'repeat':
                errors.append(f"Mismatched 'until' at line {line}, opened by '{opener}' at line {oline}")

    if stack:
        for opener, oline in stack:
            errors.append(f"Unclosed '{opener}' opened at line {oline}")

    if errors:
        print(f"FAILED with {len(errors)} errors:")
        for e in errors[:10]:
            print("  ", e)
        return False

    try:
        import sys
        sys.path.append(r'C:\Users\wilsz\Desktop\earthng\.venv\Lib\site-packages')
        import lupa
        lua = lupa.LuaRuntime()
        lua.compile(code)
        print("SUCCESS: LuaJIT compilation passed with 0 errors (under 200 locals limit verified)!")
    except ImportError:
        print("WARNING: lupa not found, skipped LuaJIT bytecode compilation check.")
    except Exception as e:
        print(f"LuaJIT compilation FAILED: {e}")
        return False

    print("SUCCESS: All Lua blocks (function, then, do, repeat, end) match perfectly!")
    return True

if __name__ == '__main__':
    verify_lua(r'mod/lua/ge/extensions/e2r/generator.lua')
