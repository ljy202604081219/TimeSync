import hashlib
import json
import re

def event_key(category,title):
    normalized=re.sub(r'[\W_]+','',title.lower())
    return hashlib.sha256((category+':'+normalized).encode()).hexdigest()

def fingerprint(result):
    # Owner-scoped uniqueness; dates prevent merging weekly recurring tasks.
    parts=[event_key(result.category,result.title),result.operation,result.deadline,result.start,result.end,result.location]
    return hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()
