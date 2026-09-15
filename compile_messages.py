import os
import re
import struct
from pathlib import Path

def unescape_po(s):
    return (s.replace('\\\\', '\x00')
             .replace('\\"', '"')
             .replace('\\n', '\n')
             .replace('\\t', '\t')
             .replace('\\r', '\r')
             .replace('\x00', '\\'))

def parse_po(content):
    entries = {}
    lines = content.splitlines()
    msgid = None
    msgstr = None
    state = None
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('msgid '):
            if msgid is not None and msgstr is not None:
                entries[msgid] = msgstr
            raw = line[6:].strip()
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            msgid = unescape_po(raw)
            msgstr = None
            state = 'msgid'
        elif line.startswith('msgstr '):
            raw = line[7:].strip()
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            msgstr = unescape_po(raw)
            state = 'msgstr'
        elif line.startswith('"') and line.endswith('"'):
            val = unescape_po(line[1:-1])
            if state == 'msgid':
                msgid += val
            elif state == 'msgstr':
                msgstr += val
                
    if msgid is not None and msgstr is not None:
        entries[msgid] = msgstr
    return entries

def compile_mo(po_path, mo_path):
    with open(po_path, 'r', encoding='utf-8') as f:
        po_content = f.read()
    
    entries = parse_po(po_content)
    
    # Sort entries by msgid as required by gettext mo format
    keys = sorted(entries.keys())
    
    # Header format:
    # 0x00: Magic (0x950412de)
    # 0x04: Format revision (0)
    # 0x08: Number of strings (N)
    # 0x0C: Offset of original strings table (O)
    # 0x10: Offset of translation strings table (T)
    # 0x14: Size of hashing table (0)
    # 0x18: Offset of hashing table (0)
    
    num_strings = len(keys)
    orig_table_offset = 28
    trans_table_offset = orig_table_offset + num_strings * 8
    
    # Now build original strings data and translation strings data
    orig_strings_data = b''
    orig_table_entries = []
    
    trans_strings_data = b''
    trans_table_entries = []
    
    current_orig_offset = trans_table_offset + num_strings * 8
    for k in keys:
        b_k = k.encode('utf-8') + b'\x00'
        orig_table_entries.append((len(b_k) - 1, current_orig_offset))
        orig_strings_data += b_k
        current_orig_offset += len(b_k)
        
    current_trans_offset = current_orig_offset
    for k in keys:
        b_v = entries[k].encode('utf-8') + b'\x00'
        trans_table_entries.append((len(b_v) - 1, current_trans_offset))
        trans_strings_data += b_v
        current_trans_offset += len(b_v)
        
    header = struct.pack(
        '<Iiiiiii',
        0x950412de, # magic
        0,          # revision
        num_strings,# number of strings
        orig_table_offset, # offset of orig table
        trans_table_offset,# offset of trans table
        0,          # hash table size
        0           # hash table offset
    )
    
    orig_table = b''.join(struct.pack('<ii', length, offset) for length, offset in orig_table_entries)
    trans_table = b''.join(struct.pack('<ii', length, offset) for length, offset in trans_table_entries)
    
    mo_data = header + orig_table + trans_table + orig_strings_data + trans_strings_data
    
    with open(mo_path, 'wb') as f:
        f.write(mo_data)
    print(f"Compiled {po_path} -> {mo_path} ({num_strings} strings)")

if __name__ == '__main__':
    base_dir = Path(__file__).resolve().parent
    for lang in ['en', 'uz']:
        po = base_dir / 'locale' / lang / 'LC_MESSAGES' / 'django.po'
        mo = base_dir / 'locale' / lang / 'LC_MESSAGES' / 'django.mo'
        if po.exists():
            compile_mo(po, mo)
        else:
            print(f"File not found: {po}")
